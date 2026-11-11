import hashlib
import re
import secrets
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..models import AuditLog, User
from ..schemas import AuditLogOut, EmailCodeIn, EmailLoginIn, LoginIn, UserCreate, UserOut, UserUpdate
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


@router.post("/email-code")
def email_code(payload: EmailCodeIn, request: Request, db: Session = Depends(get_db)):
    """发送邮箱验证码。同邮箱 60s 一条；SMTP 未配置时内网试用模式直接返回 dev_code。"""
    email = payload.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    _check_rate("emailcode:" + email + "|" + _client_ip(request))
    code = f"{secrets.randbelow(1000000):06d}"
    with _codes_lock:
        _email_codes[email] = (_hash_code(code), time.monotonic() + _CODE_TTL)
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
    with _codes_lock:
        entry = _email_codes.get(email)
        ok = bool(entry and entry[1] > time.monotonic()
                  and secrets.compare_digest(entry[0], _hash_code(payload.code.strip())))
        if ok:
            _email_codes.pop(email, None)
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

