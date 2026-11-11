"""v0.7 tests: Feishu OAuth flow (mocked HTTP), account linking, state check."""
import os
from urllib.parse import parse_qs, urlparse

os.environ["DATABASE_URL"] = "sqlite:///./v07_test.db"
os.environ["FEISHU_APP_ID"] = "cli_test_app"
os.environ["FEISHU_APP_SECRET"] = "test_secret"

if os.path.exists("./v07_test.db"):
    os.remove("./v07_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.sso import feishu as feishu_svc  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402

assert settings.feishu_app_id == "cli_test_app"
assert settings.sso_default_role == "member"

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)

# 1. 公开配置
r = client.get("/api/auth/config")
assert r.status_code == 200 and r.json()["feishu_enabled"] is True
print("auth config: OK")

# 2. 登录跳转（生成 state cookie + 飞书授权 URL）
r = client.get("/api/auth/sso/feishu/login", follow_redirects=False)
assert r.status_code in (301, 302, 307), r.text
loc = r.headers["location"]
assert "open.feishu.cn" in loc and "cli_test_app" in loc and "state=" in loc
from urllib.parse import unquote as _uq
assert "feishu/callback" in _uq(loc)
state = (client.cookies.get("llmtrace_sso") or "").split("|")[-1] or None
assert state
print("authorize redirect: OK")

# 3. state 校验失败
r = client.get("/api/auth/sso/feishu/callback", params={"code": "c", "state": "bad"}, follow_redirects=False)
assert r.status_code == 400
print("bad state rejected: OK")

# 4. mock 飞书用户信息 → 回调建号
feishu_svc.exchange = lambda code, ru: {
    "subject": "ou_abc123", "name": "李四", "email": "lisi@corp.com", "avatar": None}
with SessionLocal() as _d:
    print("USERS BEFORE:", _d.execute(__import__("sqlalchemy").text("SELECT username, is_active, sso_provider, sso_subject FROM users")).all())
r = client.get("/api/auth/sso/feishu/callback",
               params={"code": "real-code", "state": state}, follow_redirects=False)
print("CALLBACK RESP:", r.status_code, r.text[:200])
assert r.status_code in (301, 302, 307), r.text
loc = r.headers["location"]
assert loc.startswith(settings.frontend_url) and "token=" in loc
token = parse_qs(urlparse(loc).query)["token"][0]
print("callback -> jwt redirect: OK")

# 5. me：飞书新用户，默认角色 member
r = client.get("/api/auth/me", headers={"Authorization": "Bearer " + token})
assert r.status_code == 200, r.text
me = r.json()
assert me["username"] == "lisi@corp.com" and me["display_name"] == "李四"
assert me["role"] == "member" and me["sso_subject"] == "ou_abc123" and me["sso_provider"] == "feishu"
print("feishu user created: OK", me["username"])

# 6. 二次登录 → 同一账号（不重复建号）
state2 = (client.cookies.get("llmtrace_sso") or "").split("|")[-1] or None or state
r = client.get("/api/auth/sso/feishu/login", follow_redirects=False)
r = client.get("/api/auth/sso/feishu/callback",
               params={"code": "again", "state": (client.cookies.get("llmtrace_sso") or "").split("|")[-1] or None},
               follow_redirects=False)
token2 = parse_qs(urlparse(r.headers["location"]).query)["token"][0]
me2 = client.get("/api/auth/me", headers={"Authorization": "Bearer " + token2}).json()
assert me2["id"] == me["id"]
print("account linking: OK")

# 7. 审计：SSO 建号有记录；管理员可查
r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
admin_auth = {"Authorization": "Bearer " + r.json()["token"]}
actions = [(a["action"], a["target"]) for a in client.get("/api/auth/audit-logs", headers=admin_auth).json()]
assert ("user.create", "lisi@corp.com") in actions
# member 不能读审计
assert client.get("/api/auth/audit-logs", headers={"Authorization": "Bearer " + token}).status_code == 403
print("audit: OK")

engine.dispose()
print("")
print("ALL V07 TESTS PASSED")



