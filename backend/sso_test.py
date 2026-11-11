"""SSO 多 provider 测试：通用 OIDC + GitHub OAuth（mock HTTP 不可行，直接 mock exchange），
覆盖：动态 config、订阅路由、建号、账号关联、未配置 provider 404。"""
import os
from urllib.parse import parse_qs, urlparse

os.environ["DATABASE_URL"] = "sqlite:///./sso_test.db"
os.environ["SSO_OIDC_ISSUER"] = "https://idp.example.com"
os.environ["SSO_OIDC_CLIENT_ID"] = "cid"
os.environ["SSO_OIDC_CLIENT_SECRET"] = "sec"
os.environ["SSO_GITHUB_CLIENT_ID"] = "gh_cid"
os.environ["SSO_GITHUB_CLIENT_SECRET"] = "gh_sec"
os.environ["FEISHU_APP_ID"] = ""

if os.path.exists("./sso_test.db"):
    os.remove("./sso_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.sso import oidc, github  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)

# 1. config 暴露 providers（飞书未配置 → 只有 oidc/github）
r = client.get("/api/auth/config")
names = [p["name"] for p in r.json()["providers"]]
assert "oidc" in names and "github" in names and "feishu" not in names, names
print("config providers: OK", names)

# 2. OIDC authorize URL（标准路径推导）
r = client.get("/api/auth/sso/oidc/login", follow_redirects=False)
assert r.status_code in (301, 302, 307), r.text
loc = r.headers["location"]
assert loc.startswith("https://idp.example.com/authorize")
qs = parse_qs(urlparse(loc).query)
assert qs["client_id"] == ["cid"] and qs["response_type"] == ["code"]
state = (client.cookies.get("llmtrace_sso") or "").split("|")[-1]
assert state
print("oidc authorize: OK")

# 3. mock exchange → callback 建号
oidc.exchange = lambda code, ru: {
    "subject": "sub-123", "name": "王五", "email": "wangwu@corp.com", "avatar": "http://a/p.png"}
r = client.get("/api/auth/sso/oidc/callback",
               params={"code": "c1", "state": state}, follow_redirects=False)
assert r.status_code in (301, 302, 307), r.text
token1 = parse_qs(urlparse(r.headers["location"]).query)["token"][0]
me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + token1}).json()
assert me["username"] == "wangwu@corp.com" and me["sso_provider"] == "oidc" and me["sso_subject"] == "sub-123"
print("oidc create user: OK")

# 4. 二次登录同 subject → 不重复建号
r = client.get("/api/auth/sso/oidc/login", follow_redirects=False)
state2 = (client.cookies.get("llmtrace_sso") or "").split("|")[-1]
r = client.get("/api/auth/sso/oidc/callback",
               params={"code": "c2", "state": state2}, follow_redirects=False)
token2 = parse_qs(urlparse(r.headers["location"]).query)["token"][0]
me2 = client.get("/api/auth/me", headers={"Authorization": "Bearer " + token2}).json()
assert me2["id"] == me["id"]
print("oidc account linking: OK")

# 5. GitHub provider（隔离的 subject 空间：同 subject 不同 provider 是不同账号）
github.exchange = lambda code, ru: {
    "subject": "sub-123", "name": "GH User", "email": "gh@corp.com", "avatar": None}
r = client.get("/api/auth/sso/github/login", follow_redirects=False)
assert r.headers["location"].startswith("https://github.com/login/oauth/authorize")
state3 = (client.cookies.get("llmtrace_sso") or "").split("|")[-1]
r = client.get("/api/auth/sso/github/callback",
               params={"code": "c3", "state": state3}, follow_redirects=False)
token3 = parse_qs(urlparse(r.headers["location"]).query)["token"][0]
me3 = client.get("/api/auth/me", headers={"Authorization": "Bearer " + token3}).json()
assert me3["sso_provider"] == "github" and me3["id"] != me["id"]
print("github user (isolated subject space): OK")

# 6. state 校验
r = client.get("/api/auth/sso/oidc/callback", params={"code": "x", "state": "bad"},
               follow_redirects=False)
assert r.status_code == 400
print("bad state rejected: OK")

# 7. 未配置 provider 404（飞书没配 env）
r = client.get("/api/auth/sso/feishu/login", follow_redirects=False)
assert r.status_code == 404
print("unconfigured provider 404: OK")

engine.dispose()
print()
print("ALL SSO TESTS PASSED")
