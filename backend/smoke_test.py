"""Offline smoke test: SQLite + TestClient. Run: python smoke_test.py"""
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///./smoke_test.db"

if os.path.exists("./smoke_test.db"):
    os.remove("./smoke_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)

_r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
assert _r.status_code == 200, _r.text
AUTH = {"Authorization": "Bearer " + _r.json()["token"]}
print("login: OK")

# 1. health
r = client.get("/api/health")
assert r.status_code == 200 and r.json() == {"status": "ok"}, r.text
print("health: OK")

# 2. create project
r = client.post("/api/v1/projects", json={"name": "smoke"}, headers=AUTH)
assert r.status_code == 201, r.text
project = r.json()
api_key = project["api_key"]
headers = {"X-API-Key": api_key}
print("project created:", project["id"])

# 3. ingest a trace with 3 spans (chain -> tool -> llm)
now = datetime.now(timezone.utc)
root_id, tool_id = str(uuid.uuid4()), str(uuid.uuid4())
payload = {
    "name": "rag-chat",
    "session_id": "user-1",
    "status": "ok",
    "start_time": now.isoformat(),
    "end_time": (now + timedelta(milliseconds=520)).isoformat(),
    "spans": [
        {
            "id": root_id,
            "parent_span_id": None,
            "name": "rag-chat",
            "span_type": "chain",
            "input": {"question": "hi"},
            "output": {"answer": "hello"},
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(milliseconds=520)).isoformat(),
        },
        {
            "id": tool_id,
            "parent_span_id": root_id,
            "name": "retrieve",
            "span_type": "tool",
            "input": {"q": "hi"},
            "output": {"docs": 3},
            "start_time": (now + timedelta(milliseconds=10)).isoformat(),
            "end_time": (now + timedelta(milliseconds=60)).isoformat(),
        },
        {
            "parent_span_id": tool_id,
            "name": "gpt-4o-mini",
            "span_type": "llm",
            "model": "gpt-4o-mini",
            "input": [{"role": "user", "content": "hi"}],
            "output": {"role": "assistant", "content": "hello"},
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "total_tokens": 200,
            "start_time": (now + timedelta(milliseconds=70)).isoformat(),
            "end_time": (now + timedelta(milliseconds=500)).isoformat(),
        },
    ],
}
r = client.post("/api/v1/traces/ingest", json=payload, headers=headers)
assert r.status_code == 201, r.text
trace_id = r.json()["id"]
print("trace ingested:", trace_id)

# 4. list traces
r = client.get("/api/v1/traces", headers=AUTH)
assert r.status_code == 200, r.text
_page = r.json()
assert _page["total"] == 1 and len(_page["items"]) == 1, r.text
item = _page["items"][0]
assert item["name"] == "rag-chat" and item["latency_ms"] == 520 and item["total_tokens"] == 200
print("list traces: OK  (latency 520ms, 200 tokens, cost", item["cost"], ")")

# 5. trace detail with span tree
r = client.get("/api/v1/traces/" + trace_id, headers=AUTH)
assert r.status_code == 200, r.text
detail = r.json()
assert len(detail["spans"]) == 3
assert {s["span_type"] for s in detail["spans"]} == {"chain", "tool", "llm"}
print("trace detail: OK (3 spans)")

# 6. metrics overview (no date_trunc -> portable SQL)
r = client.get("/api/v1/metrics/overview", params={"hours": 24}, headers=AUTH)
assert r.status_code == 200, r.text
ov = r.json()
assert ov["total_traces"] == 1 and ov["avg_latency_ms"] == 520.0 and ov["total_tokens"] == 200
print("metrics overview: OK", ov)

# 6.5 timeseries (portable SQL, works on sqlite too)
r = client.get("/api/v1/metrics/timeseries", params={"hours": 24}, headers=AUTH)
assert r.status_code == 200, r.text
ts = r.json()
assert len(ts) == 25
assert sum(p["calls"] for p in ts) == 1
print("metrics timeseries: OK")

# 7. auth rejection
r = client.get("/api/v1/traces", headers={"X-API-Key": "wrong"})
assert r.status_code == 401
print("auth rejection: OK")

engine.dispose()
print("")
print("ALL SMOKE TESTS PASSED")



