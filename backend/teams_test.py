# -*- coding: utf-8 -*-
"""团队多租户端到端：创建团队/邀请码加入/项目隔离/跨团队不可见/邀请码轮换。"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./teams_test.db"
if os.path.exists("./teams_test.db"):
    os.remove("./teams_test.db")

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.services.security import ensure_default_admin

Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    ensure_default_admin(db)

client = TestClient(app)

# 1) 新邮箱用户登录（viewer、无团队）并创建团队 team-a（自动升级 member）
r = client.post("/api/auth/email-code", json={"email": "owner@corp.com"})
oc = r.json()["dev_code"]
r = client.post("/api/auth/email-login", json={"email": "owner@corp.com", "code": oc})
ot = r.json()["token"]
ah = {"Authorization": "Bearer " + ot}
r = client.post("/api/team", json={"name": "team-a"}, headers=ah)
assert r.status_code == 201, r.text
invite = r.json()["invite_code"]
r = client.get("/api/team", headers=ah)
assert r.json()["name"] == "team-a" and r.json()["is_owner"] is True and r.json()["invite_code"] == invite
r = client.get("/api/auth/me", headers=ah)
assert r.json()["role"] == "member", f"creator should be member: {r.json()}"
print("create team (creator auto member): OK")

# 2) admin 建项目 proj-a（自动归属 team-a）
r = client.post("/api/v1/projects", json={"name": "proj-a"}, headers=ah)
assert r.status_code == 201, r.text
proj_a = r.json()["id"]
with SessionLocal() as db:
    from app.models import Project
    assert db.get(Project, __import__("uuid").UUID(proj_a)).team_id is not None
print("project bound to team: OK")

# 3) 新邮箱用户（无团队）登录：看不到任何项目/trace
r = client.post("/api/auth/email-code", json={"email": "zhang@corp.com"})
code1 = r.json()["dev_code"]
r = client.post("/api/auth/email-login", json={"email": "zhang@corp.com", "code": code1})
zt = r.json()["token"]
zh = {"Authorization": "Bearer " + zt}
assert r.json()["user"]["team_id"] is None
r = client.get("/api/v1/projects", headers=zh)
assert r.json() == [], f"no-team user should see nothing: {r.json()}"
r = client.get("/api/v1/traces", params={"project_id": proj_a}, headers=zh)
assert r.json()["items"] == [] and r.json()["total"] == 0, "cross-team leak!"
print("no-team isolation: OK")

# 4) 凭邀请码加入团队 → 立即可见团队项目
r = client.post("/api/team/join", json={"invite_code": invite}, headers=zh)
assert r.status_code == 200, r.text
r = client.get("/api/v1/projects", headers=zh)
assert [p["name"] for p in r.json()] == ["proj-a"]
r = client.get("/api/v1/traces", params={"project_id": proj_a}, headers=zh)
assert r.status_code == 200
print("join team + visibility: OK")

# 5) 其他无团队用户：跨团队直接读被隔离
r = client.post("/api/auth/email-code", json={"email": "li@corp.com"})
code2 = r.json()["dev_code"]
r = client.post("/api/auth/email-login", json={"email": "li@corp.com", "code": code2})
lt = r.json()["token"]
lh = {"Authorization": "Bearer " + lt}
r = client.get("/api/v1/traces", params={"project_id": proj_a}, headers=lh)
assert r.json()["items"] == [], "cross-team leak!"
print("cross-team isolation: OK")

# 6) 邀请码轮换与权限：li 先凭旧码加入；li 非创建者不能轮换；轮换后旧码失效
r = client.post("/api/team/join", json={"invite_code": invite}, headers=lh)
assert r.status_code == 200, r.text  # li 凭旧码加入
r = client.post("/api/team/invite-code", headers=lh)
assert r.status_code == 403, f"non-owner must not rotate: {r.status_code} {r.text}"
print("invite rotate permission: OK")

r = client.post("/api/team/invite-code", headers=ah)
new_invite = r.json()["invite_code"]
assert new_invite != invite
print("invite rotation by owner: OK")

# 7) 轮换后旧码失效、新码可用
r = client.post("/api/auth/email-code", json={"email": "wu@corp.com"})
wu_code = r.json()["dev_code"]
r = client.post("/api/auth/email-login", json={"email": "wu@corp.com", "code": wu_code})
wt = r.json()["token"]
wh = {"Authorization": "Bearer " + wt}
r = client.post("/api/team/join", json={"invite_code": invite}, headers=wh)
assert r.status_code == 404, "old invite must be invalid after rotation"
r = client.post("/api/team/join", json={"invite_code": new_invite}, headers=wh)
assert r.status_code == 200
r = client.get("/api/v1/projects", headers=wh)
assert [p["name"] for p in r.json()] == ["proj-a"]
print("old invite invalid, new invite works: OK")

print("\nALL TEAM TESTS PASSED")
