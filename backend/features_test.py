"""Feature tests: batch ingest, export, webhook signature, audit."""
import csv
import io
import json
import os
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite:///./features_test.db"

if os.path.exists("./features_test.db"):
    os.remove("./features_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.alerting import build_webhook_body, sign_body  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)

_r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
AUTH = {"Authorization": "Bearer " + _r.json()["token"]}

# member 用户（用于审计断言）
client.post("/api/auth/users", headers=AUTH, json={
    "username": "dev5", "password": "dev5pass", "role": "member"})
MEM = {"Authorization": "Bearer " + client.post(
    "/api/auth/login", json={"username": "dev5", "password": "dev5pass"}).json()["token"]}

# 团队模型：member 建项目前先创建团队
client.post("/api/team", headers=MEM, json={"name": "v05-team"})

# 1. member 建项目（产生 project.create 审计）
r = client.post("/api/v1/projects", headers=MEM, json={"name": "v05"})
assert r.status_code == 201, r.text
project = r.json()
PID, KEY = project["id"], project["api_key"]
ING = {"X-API-Key": KEY}

# 2. 批量上报
now = datetime.now(timezone.utc)
traces = []
for i in range(3):
    traces.append({
        "name": "batch-" + str(i),
        "session_id": "s-batch",
        "start_time": now.isoformat(),
        "end_time": now.isoformat(),
        "spans": [{"name": "step", "start_time": now.isoformat(), "end_time": now.isoformat()}],
    })
r = client.post("/api/v1/traces/ingest-batch", headers=ING, json={"traces": traces})
assert r.status_code == 201 and r.json()["count"] == 3, r.text
r = client.get("/api/v1/traces", params={"project_id": PID}, headers=AUTH)
assert r.json()["total"] == 3 and len(r.json()["items"]) == 3
print("batch ingest: OK (3 traces, 1 request)")

# 3. 导出 CSV / JSON
r = client.get("/api/v1/traces/export", params={"project_id": PID, "format": "csv"}, headers=AUTH)
assert r.status_code == 200 and "name" in r.text and "batch-0" in r.text
rows = list(csv.DictReader(io.StringIO(r.text)))
assert len(rows) == 3
print("export csv: OK")

r = client.get("/api/v1/traces/export", params={"project_id": PID, "format": "json"}, headers=AUTH)
data = json.loads(r.text)
assert isinstance(data, list) and len(data) == 3 and data[0]["name"].startswith("batch-")
print("export json: OK")

# 4. 企微 / 飞书 webhook 报文 + 签名
class R:
    webhook_format = "wecom"

assert build_webhook_body(R(), "hello", {"g": 1}) == {"msgtype": "text", "text": {"content": "hello"}}
R.webhook_format = "feishu"
assert build_webhook_body(R(), "hello", {}) == {"msg_type": "text", "content": {"text": "hello"}}
sig = sign_body("s3cret", b"hello")
assert len(sig) == 64 and sig == sign_body("s3cret", b"hello") and sig != sign_body("other", b"hello")
print("wecom body + hmac signature: OK")

# 5. 带密钥的规则创建（schema 接受 webhook_secret）
r = client.post("/api/v1/alerts/rules", headers=MEM, json={
    "project_id": PID, "name": "signed", "metric_type": "avg_latency_ms",
    "threshold": 10000, "window_minutes": 60,
    "webhook_url": "https://example.com/hook", "webhook_format": "wecom",
    "webhook_secret": "s3cret"})
assert r.status_code == 201 and r.json()["webhook_secret"] == "s3cret", r.text
print("rule with webhook secret: OK")

# 6. 审计日志：project.create / rule.create / user.create 均有记录
r = client.get("/api/auth/audit-logs", headers=AUTH)
assert r.status_code == 200
actions = [a["action"] for a in r.json()]
assert "project.create" in actions and "rule.create" in actions and "user.create" in actions, actions
print("audit logs: OK", actions)

# 7. 成员不能读审计
assert client.get("/api/auth/audit-logs", headers=MEM).status_code == 403
print("audit admin-only: OK")

engine.dispose()
print("")
print("ALL FEATURES TESTS PASSED")
