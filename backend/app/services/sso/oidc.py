"""通用 OIDC 授权码登录（Google / Keycloak / Okta / 阿里云 IDaaS 等）。"""
import httpx

from ...config import settings
from .base import SSOError, _http

NAME = "oidc"
LABEL = "企业 SSO 登录"


def is_configured() -> bool:
    return bool(settings.sso_oidc_issuer and settings.sso_oidc_client_id
                and settings.sso_oidc_client_secret)


def redirect_uri(request) -> str:
    return str(request.base_url).rstrip("/") + "/api/auth/sso/oidc/callback"


def _endpoints() -> tuple[str, str, str]:
    """(authorize, token, userinfo)；显式配置优先，否则按 issuer 标准路径推导。"""
    issuer = settings.sso_oidc_issuer.rstrip("/")
    auth = settings.sso_oidc_auth_endpoint or issuer + "/authorize"
    tok = settings.sso_oidc_token_endpoint or issuer + "/token"
    ui = settings.sso_oidc_userinfo_endpoint or issuer + "/userinfo"
    return auth, tok, ui


def authorize_url(state: str, redirect_uri: str) -> str:
    auth, _, _ = _endpoints()
    from urllib.parse import urlencode
    return auth + "?" + urlencode({
        "client_id": settings.sso_oidc_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": settings.sso_oidc_scope,
        "state": state,
    })


def exchange(code: str, redirect_uri: str) -> dict:
    _, tok_url, ui_url = _endpoints()
    with _http() as client:
        tok = client.post(tok_url, data={
            "grant_type": "authorization_code",
            "client_id": settings.sso_oidc_client_id,
            "client_secret": settings.sso_oidc_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }).json()
        access = tok.get("access_token")
        if not access:
            raise SSOError(tok.get("error_description") or "OIDC code 换 token 失败")
        info = client.get(ui_url, headers={"Authorization": "Bearer " + access}).json()
    subject = info.get("sub")
    if not subject:
        raise SSOError("OIDC userinfo 未返回 sub")
    return {
        "subject": subject,
        "name": info.get("name") or info.get("preferred_username") or "SSO 用户",
        "email": info.get("email"),
        "avatar": info.get("picture"),
    }
