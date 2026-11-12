"""Analytics tests: model stats, histogram, filters, pagination, key rotation."""
import os
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///./analytics_test.db"

if os.path.exists("./analytics_test.db"):
    os.remove("./analytics_test.db")

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

client.post("/api/auth/users", headers=AUTH, json={
    "username": "dev6", "password": "dev6pass", "role": "member"})
MEM = {"Authorization": "Bearer " + client.post(
    "/api/auth/login", json={"username": "dev6", "password": "dev6pass"}).json()["token"]}

# 团队模型：member 建项目前先创建团队
client.post("/api/team", headers=MEM, json={"name": "v06-team"})

r = client.post("/api/v1/projects", headers=MEM, json={"name": "v06"})
project = r.json()
PID, KEY = project["id"], project["api_key"]
ING = {"X-API-Key": KEY}

# 1. 灌 3 条带 llm span 的 trace（不同模型/延迟/tokens）
now = datetime.now(timezone.utc)
CASES = [
    ("t1", "gpt-4o-mini", 100, 100, 50),
    ("t2", "gpt-4o-mini", 500, 200, 100),
    ("t3", "claude-3-5-haiku", 2000, 1000, 500),
]
for name, model, lat, p, c in CASES:
    start = now
    end = now + timedelta(milliseconds=lat)
    payload = {
        "name": name,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "spans": [{
            "name": model, "span_type": "llm", "model": model,
            "prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c,
            "start_time": start.isoformat(), "end_time": end.isoformat(),
        }],
    }
    r = client.post("/api/v1/traces/ingest", headers=ING, json=payload)
    assert r.status_code == 201, r.text
print("seed 3 traces: OK")

# 2. 模型统计
r = client.get("/api/v1/metrics/models", params={"hours": 24, "project_id": PID}, headers=AUTH)
assert r.status_code == 200, r.text
stats = {s["model"]: s for s in r.json()}
assert len(stats) == 2, stats
assert stats["gpt-4o-mini"]["calls"] == 2
assert stats["gpt-4o-mini"]["total_tokens"] == 450
assert stats["gpt-4o-mini"]["cost"] > 0
assert stats["claude-3-5-haiku"]["calls"] == 1
# 按成本降序：gpt-4o-mini 成本 (150*0.15+300*0.6)/1e6 ≈ 0.0002025 < claude (1000*3+500*15)/1e6 = 0.0105
assert r.json()[0]["model"] == "claude-3-5-haiku"
print("model stats: OK")

# 3. 延迟直方图
r = client.get("/api/v1/metrics/latency-histogram", params={"hours": 24, "project_id": PID}, headers=AUTH)
assert r.status_code == 200
hist = r.json()
assert sum(b["count"] for b in hist) == 3
assert len(hist) > 0
print("latency histogram: OK", len(hist), "buckets")

# 4. 高级筛选
r = client.get("/api/v1/traces", params={"project_id": PID, "min_latency": 400}, headers=AUTH)
assert r.json()["total"] == 2, r.text
r = client.get("/api/v1/traces", params={"project_id": PID, "model": "gpt-4o-mini"}, headers=AUTH)
assert r.json()["total"] == 2
r = client.get("/api/v1/traces", params={"project_id": PID, "span_type": "llm"}, headers=AUTH)
assert r.json()["total"] == 3
r = client.get("/api/v1/traces", params={"project_id": PID, "min_latency": 400, "model": "gpt-4o-mini"}, headers=AUTH)
assert r.json()["total"] == 1
r = client.get("/api/v1/traces", params={"project_id": PID, "model": "no-such"}, headers=AUTH)
assert r.json()["total"] == 0
print("advanced filters: OK")

# 5. 分页
r = client.get("/api/v1/traces", params={"project_id": PID, "limit": 2}, headers=AUTH)
assert r.json()["total"] == 3 and len(r.json()["items"]) == 2
r = client.get("/api/v1/traces", params={"project_id": PID, "limit": 2, "offset": 2}, headers=AUTH)
assert len(r.json()["items"]) == 1
print("pagination: OK")

# 6. Key 轮换（member 403 / admin 200 / 旧 Key 失效）
r = client.post(f"/api/v1/projects/{PID}/rotate-key", headers=MEM)
assert r.status_code == 403
r = client.post(f"/api/v1/projects/{PID}/rotate-key", headers=AUTH)
assert r.status_code == 200, r.text
new_key = r.json()["api_key"]
assert new_key != KEY
r = client.post("/api/v1/traces/ingest", headers=ING, json={
    "name": "old-key", "start_time": now.isoformat(), "end_time": now.isoformat(),
    "spans": [{"name": "x", "start_time": now.isoformat(), "end_time": now.isoformat()}]})
assert r.status_code == 401
r = client.post("/api/v1/traces/ingest", headers={"X-API-Key": new_key}, json={
    "name": "new-key", "start_time": now.isoformat(), "end_time": now.isoformat(),
    "spans": [{"name": "x", "start_time": now.isoformat(), "end_time": now.isoformat()}]})
assert r.status_code == 201
print("api key rotation: OK")

# 7. 审计包含轮换记录
actions = [a["action"] for a in client.get("/api/auth/audit-logs", headers=AUTH).json()]
assert "project.rotate_key" in actions
print("rotate audited: OK")

engine.dispose()
print("")
print("ALL ANALYTICS TESTS PASSED")
