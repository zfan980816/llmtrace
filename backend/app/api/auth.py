import hashlib
import re
import secrets
import threading
import time
import uuid

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..models import AuditLog, User
from ..schemas import (AuditLogOut, EmailCodeIn, EmailLoginIn, LoginIn,
                       PasswordResetIn, RegisterIn, UserCreate, UserOut, UserUpdate)
from ..services.audit import record_audit
from ..services.email import send_email_code
from ..services.security import (
    create_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,)

router = APIRouter(prefix="/api/auth", tags=["auth"])
VALID_ROLES = ("admin", "member", "viewer")

# ---- 登录限速：同 用户名+IP 每 60s 窗口最多 5 次失败，成功登录清零 ----
_FAIL_WINDOW = 60.0
_FAIL_LIMIT = 5
_login_fails: dict[str, list[float]] = {}
_fails_lock = threading.Lock()


def _client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate(key: str) -> None:
    now = time.monotonic()
    with _fails_lock:
        hits = [t for t in _login_fails.get(key, []) if now - t < _FAIL_WINDOW]
        _login_fails[key] = hits
        if len(hits) >= _FAIL_LIMIT:
            retry = int(_FAIL_WINDOW - (now - hits[0])) + 1
            raise HTTPException(status_code=429, detail=f"尝试过于频繁，请 {retry}s 后重试")


def _record_fail(key: str) -> None:
    with _fails_lock:
        _login_fails.setdefault(key, []).append(time.monotonic())


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CODE_TTL = 600  # 验证码 10 分钟
_email_codes: dict[str, tuple[str, float]] = {}  # email -> (sha256, expiry)
_codes_lock = threading.Lock()


def _hash_code(c: str) -> str:
    return hashlib.sha256(c.encode()).hexdigest()


# ---- 注册/找回密码：发码冷却（同 邮箱+用途 60s）----
_SEND_COOLDOWN = 60.0
_send_cooldowns: dict[str, float] = {}


def _cooldown_left(key: str) -> int:
    with _codes_lock:
        until = _send_cooldowns.get(key)
        if until and until > time.monotonic():
            return int(until - time.monotonic()) + 1
    return 0


def _mark_sent(key: str) -> None:
    with _codes_lock:
        _send_cooldowns[key] = time.monotonic() + _SEND_COOLDOWN


def _issue_code(email: str, purpose: str) -> str:
    code = f"{secrets.randbelow(1000000):06d}"
    with _codes_lock:
        _email_codes[f"{purpose}:{email}"] = (_hash_code(code), time.monotonic() + _CODE_TTL)
    return code


def _verify_consume(email: str, purpose: str, code: str) -> bool:
    key = f"{purpose}:{email}"
    with _codes_lock:
        entry = _email_codes.get(key)
        ok = bool(entry and entry[1] > time.monotonic()
                  and secrets.compare_digest(entry[0], _hash_code(code.strip())))
        if ok:
            _email_codes.pop(key, None)
    return ok


@router.post("/email-code")
def email_code(payload: EmailCodeIn, request: Request, db: Session = Depends(get_db)):
    """发送邮箱验证码。同邮箱 60s 一条；SMTP 未配置时内网试用模式直接返回 dev_code。"""
    email = payload.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    _check_rate("emailcode:" + email + "|" + _client_ip(request))
    code = _issue_code(email, "login")
    sent = send_email_code(email, code)
    if not sent:
        return {"sent": True, "dev_code": code}  # 内网试用：SMTP 未配置时直接显示验证码
    return {"sent": True}


@router.post("/email-login")
def email_login(payload: EmailLoginIn, request: Request, db: Session = Depends(get_db)):
    """邮箱 + 验证码登录：新邮箱自动注册为 viewer（可查看监控），管理员可提权。"""
    email = payload.email.strip().lower()
    key = "emaillogin:" + email + "|" + _client_ip(request)
    _check_rate(key)
    ok = _verify_consume(email, "login", payload.code)
    if not ok:
        _record_fail(key)
        raise HTTPException(status_code=401, detail="验证码错误或已过期")
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = db.query(User).filter(User.username == email).first()
        if user is not None and not user.email:
            user.email = email
    if user is None:
        local = email.split("@")[0][:40] or "user"
        username = local
        if db.query(User).filter(User.username == username).first() is not None:
            username = f"{local}-{secrets.token_hex(2)}"
        user = User(username=username, display_name=local[:30], email=email,
                    role=settings.email_default_role, password_hash="", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    with _fails_lock:
        _login_fails.pop(key, None)
    return {"token": create_token(user), "user": UserOut.model_validate(user)}




@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    key = payload.username.lower() + "|" + _client_ip(request)
    _check_rate(key)
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        _record_fail(key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    with _fails_lock:
        _login_fails.pop(key, None)
    return {"token": create_token(user), "user": UserOut.model_validate(user)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@router.patch("/me/password")
def change_own_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=422, detail="新密码至少 8 位")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    record_audit(db, user, "user.change_password", user.username, {})
    return {"ok": True}




@router.get("/users", response_model=list[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {VALID_ROLES}")
    exists = db.query(User).filter(User.username == payload.username).first()
    if exists:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=payload.username,
        display_name=payload.display_name or payload.username,
        role=payload.role,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit(db, admin, "user.create", user.username, {"role": user.role})
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = payload.model_dump(exclude_unset=True)
    if "role" in data:
        if data["role"] not in VALID_ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of {VALID_ROLES}")
        if user.id == admin.id and data["role"] != "admin":
            raise HTTPException(status_code=400, detail="不能降级自己的管理员角色")
        user.role = data.pop("role")
    if "is_active" in data:
        if user.id == admin.id and data["is_active"] is False:
            raise HTTPException(status_code=400, detail="不能停用自己的账号")
        user.is_active = data.pop("is_active")
    if data.get("password"):
        user.password_hash = hash_password(data.pop("password"))
    if data.get("display_name") is not None:
        user.display_name = data.pop("display_name")
    db.commit()
    db.refresh(user)
    record_audit(db, admin, "user.update", user.username,
                 payload.model_dump(exclude_unset=True, exclude={"password"}))
    db.commit()
    return user


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    limit: int = 100,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).all()



# ---- 邮箱注册（验码建号）与忘记密码/重置（参考 travel_plan 流程口径）----

def _user_by_email(db: Session, email: str) -> User | None:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        u = db.query(User).filter(User.username == email).first()
        if u is not None and not u.email:
            return u
    return user


@router.post("/register/send-code")
def register_send_code(payload: EmailCodeIn, request: Request, db: Session = Depends(get_db)):
    """注册验证码：已注册邮箱直接 400（注册流程本就会暴露该状态，提前明示换体验）。"""
    email = payload.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    if _user_by_email(db, email) is not None:
        raise HTTPException(status_code=400, detail="该邮箱已注册，请直接登录")
    left = _cooldown_left(f"register:{email}")
    if left:
        raise HTTPException(status_code=429, detail=f"发送太频繁，请 {left}s 后再试")
    _check_rate("sendcode:register:" + email + "|" + _client_ip(request))
    code = _issue_code(email, "register")
    _mark_sent(f"register:{email}")
    sent = send_email_code(email, code)
    if not sent:
        return {"sent": True, "dev_code": code}
    return {"sent": True}


@router.post("/register")
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    """验码 → 建号（唯一注册入口，带密码；成功即登录）。"""
    email = payload.email.strip().lower()
    key = "register:" + email + "|" + _client_ip(request)
    _check_rate(key)
    if len(payload.password) < 8:
        raise HTTPException(status_code=422, detail="密码至少 8 位")
    if not _verify_consume(email, "register", payload.code):
        _record_fail(key)
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    if _user_by_email(db, email) is not None:
        raise HTTPException(status_code=400, detail="该邮箱已注册")
    username = (payload.username or email.split("@")[0])[:40]
    if db.query(User).filter(User.username == username).first() is not None:
        username = f"{username}-{secrets.token_hex(2)}"
    user = User(username=username, display_name=(payload.username or username)[:30],
                email=email, role=settings.email_default_role,
                password_hash=hash_password(payload.password), is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    record_audit(db, user, "user.register", user.username, {"email": email})
    db.commit()
    with _fails_lock:
        _login_fails.pop(key, None)
    return {"token": create_token(user), "user": UserOut.model_validate(user)}


@router.post("/forgot/send-code")
def forgot_send_code(payload: EmailCodeIn, request: Request, db: Session = Depends(get_db)):
    """忘记密码发码：响应恒 {sent:true}（防枚举注册名单）。"""
    email = payload.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    left = _cooldown_left(f"reset:{email}")
    if left:
        raise HTTPException(status_code=429, detail=f"发送太频繁，请 {left}s 后再试")
    user = _user_by_email(db, email)
    if user is not None:
        _check_rate("sendcode:reset:" + email + "|" + _client_ip(request))
        code = _issue_code(email, "reset")
        _mark_sent(f"reset:{email}")
        sent = send_email_code(email, code)
        if not sent:
            return {"sent": True, "dev_code": code}
    else:
        _mark_sent(f"reset:{email}")
    return {"sent": True}


@router.post("/reset")
def reset_password(payload: PasswordResetIn, request: Request, db: Session = Depends(get_db)):
    """凭码重置密码（旧密码立即失效）。"""
    email = payload.email.strip().lower()
    key = "reset:" + email + "|" + _client_ip(request)
    _check_rate(key)
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=422, detail="新密码至少 8 位")
    if not _verify_consume(email, "reset", payload.code):
        _record_fail(key)
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    user = _user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    record_audit(db, user, "user.reset_password", user.username, {})
    db.commit()
    with _fails_lock:
        _login_fails.pop(key, None)
    return {"ok": True}
