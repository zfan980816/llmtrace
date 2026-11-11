"""Sessions endpoints test (SQLite). Run: python sessions_test.py"""
import os
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///./sessions_test.db"

if os.path.exists("./sessions_test.db"):
    os.remove("./sessions_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)

_r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
AUTH = {"Authorization": "Bearer " + _r.json()["token"]}

r = client.post("/api/v1/projects", json={"name": "sess"}, headers=AUTH)
headers = AUTH
ING = {"X-API-Key": r.json()["api_key"]}
PID = r.json()["id"]

now = datetime.now(timezone.utc)
for i in range(3):
    start = now + timedelta(seconds=i)
    end = start + timedelta(milliseconds=100)
    payload = {
        "name": "turn-" + str(i),
        "session_id": "conv-1",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "spans": [{"name": "turn-" + str(i), "start_time": start.isoformat(), "end_time": end.isoformat()}],
    }
    assert client.post("/api/v1/traces/ingest", json=payload, headers=ING).status_code == 201

# one trace without session -> must not appear in sessions
payload = {
    "name": "no-session",
    "start_time": now.isoformat(),
    "end_time": now.isoformat(),
    "spans": [{"name": "x", "start_time": now.isoformat(), "end_time": now.isoformat()}],
}
assert client.post("/api/v1/traces/ingest", json=payload, headers=ING).status_code == 201

r = client.get("/api/v1/sessions", params={"project_id": PID}, headers=headers)
assert r.status_code == 200 and len(r.json()) == 1, r.text
s = r.json()[0]
assert s["session_id"] == "conv-1" and s["trace_count"] == 3
print("sessions list: OK", s)

r = client.get("/api/v1/sessions/conv-1", params={"project_id": PID}, headers=headers)
assert r.status_code == 200 and len(r.json()) == 3, r.text
print("session detail: OK (3 traces in order)")

engine.dispose()
print("")
print("ALL SESSION TESTS PASSED")


