import secrets
import sys
from pathlib import Path

from pydantic_settings import BaseSettings

_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_JWT_SECRET = "dev-secret-change-me-with-env-JWT_SECRET-32b+"


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://llmtrace:llmtrace@localhost:5432/llmtrace"
    cors_origins: str = "http://localhost:5173"
    frontend_url: str = "http://127.0.0.1:5173"
    jwt_secret: str = DEFAULT_JWT_SECRET
    token_expire_hours: int = 72
    static_dir: str = str(_REPO_ROOT / "frontend" / "dist")
    # production=true 时：使用默认 JWT_SECRET 将拒绝启动（防止密钥泄漏进生产）
    production: bool = False
    # ---- SSO 登录（全部可选；未配置的 provider 登录页自动隐藏）----
    # 飞书（开放平台企业自建应用）
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_redirect_uri: str = ""      # 留空则按当前请求自动推导
    # 通用 OIDC（Google / Keycloak / 阿里云 IDaaS / Okta 等）
    sso_oidc_issuer: str = ""          # 如 https://accounts.google.com
    sso_oidc_client_id: str = ""
    sso_oidc_client_secret: str = ""
    sso_oidc_scope: str = "openid profile email"
    # 端点留空则按 issuer + 标准路径推导
    sso_oidc_auth_endpoint: str = ""
    sso_oidc_token_endpoint: str = ""
    sso_oidc_userinfo_endpoint: str = ""
    # GitHub OAuth App
    sso_github_client_id: str = ""
    sso_github_client_secret: str = ""
    # SSO 新用户默认角色
    sso_default_role: str = "member"
    # ---- 邮箱验证码登录（SMTP）----
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""           # 发件人地址，如 llmtrace@corp.com
    email_default_role: str = "viewer"  # 新邮箱首次登录的默认角色（可看监控）


settings = Settings()

if settings.jwt_secret == DEFAULT_JWT_SECRET:
    if settings.production:
        print(
            "FATAL: JWT_SECRET 仍是默认值。生产环境（PRODUCTION=true）必须通过环境变量设置强随机 JWT_SECRET。",
            file=sys.stderr,
        )
        sys.exit(1)
    # 开发/演示：随机生成临时密钥，每次重启后所有已签发 token 失效
    settings.jwt_secret = secrets.token_urlsafe(48)

