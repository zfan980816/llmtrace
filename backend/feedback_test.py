"""Feedback tests: create / list / delete / permission."""
import os
os.environ["DATABASE_URL"] = "sqlite:///./fb_test.db"
if os.path.exists("./fb_test.db"):
    os.remove("./fb_test.db")

from fastapi.testclient import TestClient  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
import uuid  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)

AUTH = {}
def login(u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["token"]}

admin = login("admin", "admin123")

# member + viewer
client.post("/api/auth/users", headers=admin, json={"username": "m1", "password": "pw123456", "role": "member"})
client.post("/api/auth/users", headers=admin, json={"username": "v1", "password": "pw123456", "role": "viewer"})
member = login("m1", "pw123456")
viewer = login("v1", "pw123456")

proj = client.post("/api/v1/projects", headers=admin, json={"name": "fb-proj"}).json()
now = datetime.now(timezone.utc)
tid = client.post("/api/v1/traces/ingest",
                  headers={"X-API-Key": proj["api_key"]},
                  json={"name": "t1", "status": "ok",
                        "start_time": now.isoformat(),
                        "end_time": (now + timedelta(milliseconds=100)).isoformat(),
                        "spans": [{"name": "root", "span_type": "chain",
                                   "start_time": now.isoformat(),
                                   "end_time": (now + timedelta(milliseconds=100)).isoformat()}]}).json()["id"]

# 1. invalid score
r = client.post("/api/v1/feedback", headers=member,
                json={"trace_id": tid, "score": 5})
assert r.status_code == 422, r.text
print("invalid score rejected: OK")

# 2. member creates thumbs-down with comment
r = client.post("/api/v1/feedback", headers=member,
                json={"trace_id": tid, "score": -1, "comment": "回答编造了天气"})
assert r.status_code == 201, r.text
fid = r.json()["id"]
assert r.json()["user_name"] == "m1"
print("member feedback created: OK")

# 3. admin thumbs up
r = client.post("/api/v1/feedback", headers=admin, json={"trace_id": tid, "score": 1})
assert r.status_code == 201
print("admin feedback created: OK")

# 4. list (member can view)
r = client.get("/api/v1/feedback", headers=member, params={"trace_id": tid})
assert r.status_code == 200 and len(r.json()) == 2
scores = sorted(f["score"] for f in r.json())
assert scores == [-1, 1]
print("list: OK", scores)

# 5. viewer (read-only) CANNOT create
r = client.post("/api/v1/feedback", headers=viewer, json={"trace_id": tid, "score": 1})
assert r.status_code == 403, r.text
print("viewer blocked: OK")

# 6. member cannot delete admin's feedback
admin_fb = [f for f in client.get("/api/v1/feedback", headers=member, params={"trace_id": tid}).json() if f["score"] == 1][0]
r = client.delete("/api/v1/feedback/" + admin_fb["id"], headers=member)
assert r.status_code == 403, r.text
print("cross-user delete blocked: OK")

# 7. member deletes own feedback
r = client.delete("/api/v1/feedback/" + fid, headers=member)
assert r.status_code == 204, r.text
r = client.get("/api/v1/feedback", headers=member, params={"trace_id": tid})
assert len(r.json()) == 1
print("self delete: OK")

# 8. unknown trace
r = client.post("/api/v1/feedback", headers=member, json={"trace_id": str(uuid.uuid4()), "score": 1})
assert r.status_code == 404
print("unknown trace: OK")

engine.dispose()
print()
print("ALL FEEDBACK TESTS PASSED")
