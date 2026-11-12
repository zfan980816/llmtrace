"""邮箱注册 + 忘记密码/重置 全流程测试（参考 travel_plan 口径）。"""
import os, pathlib, subprocess, sys, time, json, urllib.request, urllib.error

backend = pathlib.Path(__file__).parent
db_file = backend / "_register_test.db"
if db_file.exists():
    db_file.unlink()

env = os.environ.copy()
env["DATABASE_URL"] = f"sqlite:///{db_file}"
env["JWT_SECRET"] = "register-test-secret"

r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   cwd=backend, env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stderr[-1200:]

server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
     "--port", "18896", "--log-level", "error"],
    cwd=backend, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:18896/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        print("SERVER DID NOT START"); sys.exit(1)

    def call(method, path, body=None, token=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:18896{path}",
            data=json.dumps(body).encode() if body else None, method=method,
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    EMAIL = "newuser@example.com"

    # 1. 已注册邮箱（admin 默认无邮箱；用一个不存在的邮箱先发注册码）
    c, r = call("POST", "/api/auth/register/send-code", {"email": EMAIL})
    assert c == 200 and r.get("dev_code"), f"send-code dev: {c} {r}"
    code = r["dev_code"]
    print("register send-code (dev): OK")

    # 2. 冷却 60s 内再发 → 429
    c, r = call("POST", "/api/auth/register/send-code", {"email": EMAIL})
    assert c == 429, f"cooldown expected 429, got {c} {r}"
    print("send-code cooldown: 429 OK")

    # 3. 错误验证码 → 400
    c, r = call("POST", "/api/auth/register", {"email": EMAIL, "code": "000000", "password": "password123"})
    assert c == 400, f"bad code expected 400, got {c} {r}"
    print("bad code: 400 OK")

    # 4. 弱密码 → 422（用正确验证码）
    c, r = call("POST", "/api/auth/register", {"email": EMAIL, "code": code, "password": "short"})
    assert c == 422, f"weak pwd expected 422, got {c} {r}"
    print("weak password: 422 OK")

    # 5. 正确注册 → 200 + token（码已在步骤4被消费？不——步骤4在校验密码前没消费码。
    #    注册端点先验密码长度再消费码，所以码还有效）
    c, r = call("POST", "/api/auth/register", {"email": EMAIL, "code": code, "password": "password123"})
    assert c == 200 and r.get("token"), f"register: {c} {r}"
    tok = r["token"]
    assert r["user"]["role"] == "viewer"
    print("register: OK (viewer, auto-login)")

    # 6. 重复注册同邮箱 → 400
    c, r = call("POST", "/api/auth/register/send-code", {"email": EMAIL})
    assert c == 400 and "已注册" in r.get("detail", ""), f"dup send-code: {c} {r}"
    print("dup email send-code: 400 OK")

    # 7. 密码登录（注册时设的密码）
    c, r = call("POST", "/api/auth/login", {"username": EMAIL, "password": "password123"})
    # 登录用的是 username 字段——注册时 username 是邮箱 local part
    assert c == 401, f"login by email-as-username should 401, got {c}"
    username = "newuser"
    c, r = call("POST", "/api/auth/login", {"username": username, "password": "password123"})
    assert c == 200, f"password login: {c} {r}"
    print("password login after register: OK")

    # 8. 忘记密码（存在邮箱 → 真发，dev 模式返回码）
    c, r = call("POST", "/api/auth/forgot/send-code", {"email": EMAIL})
    assert c == 200, f"forgot: {c} {r}"
    reset_code = r.get("dev_code")
    assert reset_code, f"dev reset code missing: {r}"
    print("forgot send-code: OK")

    # 9. 忘记密码（不存在邮箱 → 恒 sent:true 防枚举，无 dev_code）
    c, r = call("POST", "/api/auth/forgot/send-code", {"email": "ghost@example.com"})
    assert c == 200 and r == {"sent": True}, f"anti-enum: {c} {r}"
    print("forgot anti-enumeration: OK")

    # 10. 重置密码 → 旧密码失效，新密码可用
    c, r = call("POST", "/api/auth/reset", {"email": EMAIL, "code": reset_code, "new_password": "newpass98765"})
    assert c == 200, f"reset: {c} {r}"
    c, r = call("POST", "/api/auth/login", {"username": username, "password": "password123"})
    assert c == 401, "old password should fail"
    c, r = call("POST", "/api/auth/login", {"username": username, "password": "newpass98765"})
    assert c == 200, f"new password login: {c} {r}"
    print("password reset: OK (old invalid, new works)")

    # 11. 已有邮箱密码登录不受邮箱验证码登录影响
    c, r = call("POST", "/api/auth/email-code", {"email": "someoneelse@example.com"})
    assert c == 200 and r.get("dev_code")
    c, r = call("POST", "/api/auth/email-login", {"email": "someoneelse@example.com", "code": r["dev_code"]})
    assert c == 200
    print("email-code login still works: OK")

    print("\nALL REGISTER TESTS PASSED")
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
    db_file.unlink(missing_ok=True)
