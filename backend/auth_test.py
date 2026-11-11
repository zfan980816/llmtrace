"""Auth / RBAC / masking / retention tests (SQLite). Run: python auth_test.py"""
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///./auth_test.db"

if os.path.exists("./auth_test.db"):
    os.remove("./auth_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.retention import cleanup_expired  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)

# 1. login
r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
assert r.status_code == 200, r.text
AUTH = {"Authorization": "Bearer " + r.json()["token"]}
assert r.json()["user"]["role"] == "admin"
print("admin login: OK")

# wrong password
r = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
assert r.status_code == 401
print("wrong password rejected: OK")

# 2. create member + viewer
r = client.post("/api/auth/users", headers=AUTH, json={
    "username": "dev1", "display_name": "开发者", "password": "dev12345", "role": "member"})
assert r.status_code == 201, r.text
r = client.post("/api/auth/users", headers=AUTH, json={
    "username": "view1", "display_name": "访客", "password": "view12345", "role": "viewer"})
assert r.status_code == 201
print("users created: OK")

# duplicate username
r = client.post("/api/auth/users", headers=AUTH, json={
    "username": "dev1", "password": "dev12345", "role": "member"})
assert r.status_code == 409
print("duplicate username rejected: OK")

# 3. member login + viewer login
mtoken = client.post("/api/auth/login", json={"username": "dev1", "password": "dev12345"}).json()["token"]
vtoken = client.post("/api/auth/login", json={"username": "view1", "password": "view12345"}).json()["token"]
MEM = {"Authorization": "Bearer " + mtoken}
VIEW = {"Authorization": "Bearer " + vtoken}

# viewer cannot create project (RBAC)
r = client.post("/api/v1/projects", headers=VIEW, json={"name": "nope"})
assert r.status_code == 403, r.text
# member creates a team first (team model: projects belong to teams)
r = client.post("/api/team", headers=MEM, json={"name": "dev-team"})
assert r.status_code == 201, r.text
invite = r.json()["invite_code"]
# viewer joins the same team via invite code (then can read team data)
r = client.post("/api/team/join", headers=VIEW, json={"invite_code": invite})
assert r.status_code == 200, r.text
# member CAN create project
r = client.post("/api/v1/projects", headers=MEM, json={"name": "team-a"})
assert r.status_code == 201, r.text
project = r.json()
PID = project["id"]
print("RBAC project creation: OK (viewer 403, member 201)")

# 4. ingest (API key) then viewer can read
now = datetime.now(timezone.utc)
ing = {"X-API-Key": project["api_key"]}
r = client.post("/api/v1/traces/ingest", headers=ing, json={
    "name": "chat", "session_id": "s1",
    "input": {"question": "我的手机号是 13812345678，邮箱 foo@bar.com"},
    "start_time": now.isoformat(), "end_time": now.isoformat(),
    "spans": [{"name": "chat", "start_time": now.isoformat(), "end_time": now.isoformat()}],
})
assert r.status_code == 201, r.text
r = client.get("/api/v1/traces", headers=VIEW)
assert r.status_code == 200 and len(r.json()["items"]) == 1
print("viewer read traces: OK")

# 5. member cannot manage users
r = client.get("/api/auth/users", headers=MEM)
assert r.status_code == 403
print("member blocked from user management: OK")

# 6. masking: enable on project, ingest PII, verify masked
r = client.patch(f"/api/v1/projects/{PID}", headers=AUTH, json={"mask_pii": True})
assert r.status_code == 200 and r.json()["mask_pii"] is True, r.text
r = client.post("/api/v1/traces/ingest", headers=ing, json={
    "name": "chat-pii",
    "input": {"question": "手机 13998887777 邮箱 a.b@corp.com"},
    "start_time": now.isoformat(), "end_time": now.isoformat(),
    "spans": [{"name": "x", "input": {"note": "身份证 110101199003074258"},
               "start_time": now.isoformat(), "end_time": now.isoformat()}],
})
assert r.status_code == 201
tid = r.json()["id"]
r = client.get("/api/v1/traces/" + tid, headers=AUTH)
detail = r.json()
assert "13998887777" not in str(detail["input"]), detail["input"]
assert "[phone]" in str(detail["input"]) and "[email]" in str(detail["input"])
assert "110101199003074258" not in str(detail["spans"][0]["input"])
assert "[id]" in str(detail["spans"][0]["input"])
print("server-side PII masking: OK")

# 7. viewer cannot create alert rule; member can
r = client.post("/api/v1/alerts/rules", headers=VIEW, json={
    "project_id": PID, "name": "x", "metric_type": "error_rate", "threshold": 0.5, "window_minutes": 5})
assert r.status_code == 403
r = client.post("/api/v1/alerts/rules", headers=MEM, json={
    "project_id": PID, "name": "err-high", "metric_type": "error_rate", "threshold": 0.5, "window_minutes": 60})
assert r.status_code == 201, r.text
print("RBAC alert rules: OK (viewer 403, member 201)")

# 8. retention: set 7 days, backdate a trace, run cleanup
r = client.patch(f"/api/v1/projects/{PID}", headers=AUTH, json={"retention_days": 7})
assert r.status_code == 200
old = datetime.now(timezone.utc) - timedelta(days=10)
from app.models import Span, Trace  # noqa: E402
with SessionLocal() as db:
    t = Trace(project_id=uuid.UUID(PID), name="old", start_time=old, end_time=old, latency_ms=0)

    db.add(t)
    db.flush()
    db.add(Span(trace_id=t.id, name="s", start_time=old, end_time=old))
    db.commit()
    old_id = t.id
removed = 0
with SessionLocal() as db:
    removed = cleanup_expired(db)
with SessionLocal() as db:
    assert db.get(Trace, old_id) is None
assert removed >= 1
print("retention cleanup: OK (removed", removed, ")")

# 9. disable user -> token rejected
users = client.get("/api/auth/users", headers=AUTH).json()
dev = next(u for u in users if u["username"] == "dev1")
r = client.patch(f"/api/auth/users/{dev['id']}", headers=AUTH, json={"is_active": False})
assert r.status_code == 200
r = client.get("/api/v1/traces", headers=MEM)
assert r.status_code == 401
print("disabled user token rejected: OK")

engine.dispose()
print("")
print("ALL AUTH TESTS PASSED")


