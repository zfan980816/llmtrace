# -*- coding: utf-8 -*-
"""邮箱验证码登录端到端：发码 -> 登录自动建号(viewer) -> 验证码一次性 -> 错误码拒绝。"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./email_login_test.db"
if os.path.exists("./email_login_test.db"):
    os.remove("./email_login_test.db")

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.services.security import ensure_default_admin

Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    ensure_default_admin(db)

client = TestClient(app)

# 1) 发验证码（SMTP 未配置 -> 内网试用模式返回 dev_code）
r = client.post("/api/auth/email-code", json={"email": "zhang@corp.com"})
assert r.status_code == 200, r.text
dev = r.json()
assert dev["sent"] is True and len(dev["dev_code"]) == 6
print("send code (dev mode): OK")

# 2) 验证码登录：新邮箱自动建号，默认 viewer
r = client.post("/api/auth/email-login", json={"email": "zhang@corp.com", "code": dev["dev_code"]})
assert r.status_code == 200, r.text
data = r.json()
assert data["user"]["role"] == "viewer"
assert data["user"]["email"] == "zhang@corp.com"
assert data["token"]
print("email login + auto signup (viewer): OK")

# 3) 验证码一次性
r = client.post("/api/auth/email-login", json={"email": "zhang@corp.com", "code": dev["dev_code"]})
assert r.status_code == 401
print("code single-use: OK")

# 4) 错误验证码
client.post("/api/auth/email-code", json={"email": "zhang@corp.com"})
r = client.post("/api/auth/email-login", json={"email": "zhang@corp.com", "code": "000000"})
assert r.status_code == 401
print("wrong code rejected: OK")

# 5) 重复发码：旧码失效、新码可用；已存在账号角色保持 viewer
code_a = client.post("/api/auth/email-code", json={"email": "zhang@corp.com"}).json()["dev_code"]
code_b = client.post("/api/auth/email-code", json={"email": "zhang@corp.com"}).json()["dev_code"]
r = client.post("/api/auth/email-login", json={"email": "zhang@corp.com", "code": code_a})
assert r.status_code == 401  # 旧码被覆盖
r = client.post("/api/auth/email-login", json={"email": "zhang@corp.com", "code": code_b})
assert r.status_code == 200 and r.json()["user"]["role"] == "viewer"
print("re-issue code: old invalid, new works: OK")

# 6) token 可访问受保护接口
token = data["token"]
r = client.get("/api/auth/me", headers={"Authorization": "Bearer " + token})
assert r.status_code == 200 and r.json()["email"] == "zhang@corp.com"
print("token works on /me: OK")

print("\nALL EMAIL LOGIN TESTS PASSED")
