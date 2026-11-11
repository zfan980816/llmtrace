"""GitHub OAuth App 登录。"""
import httpx

from ...config import settings
from .base import SSOError, _http

NAME = "github"
LABEL = "GitHub 登录"
AUTHORIZE = "https://github.com/login/oauth/authorize"
TOKEN = "https://github.com/login/oauth/access_token"
USER = "https://api.github.com/user"
EMAILS = "https://api.github.com/user/emails"


def is_configured() -> bool:
    return bool(settings.sso_github_client_id and settings.sso_github_client_secret)


def redirect_uri(request) -> str:
    return str(request.base_url).rstrip("/") + "/api/auth/sso/github/callback"


def authorize_url(state: str, redirect_uri: str) -> str:
    from urllib.parse import urlencode
    return AUTHORIZE + "?" + urlencode({
        "client_id": settings.sso_github_client_id,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
    })


def exchange(code: str, redirect_uri: str) -> dict:
    with _http() as client:
        tok = client.post(TOKEN, data={
            "client_id": settings.sso_github_client_id,
            "client_secret": settings.sso_github_client_secret,
            "code": code,
        }, headers={"Accept": "application/json"}).json()
        access = tok.get("access_token")
        if not access:
            raise SSOError(tok.get("error_description") or "GitHub code 换 token 失败")
        headers = {"Authorization": "Bearer " + access}
        info = client.get(USER, headers=headers).json()
        if not info.get("id"):
            raise SSOError("GitHub 未返回用户信息")
        email = info.get("email")
        if not email:
            emails = client.get(EMAILS, headers=headers).json()
            for e in emails if isinstance(emails, list) else []:
                if e.get("primary"):
                    email = e.get("email")
                    break
    return {
        "subject": str(info["id"]),
        "name": info.get("name") or info.get("login") or "GitHub 用户",
        "email": email,
        "avatar": info.get("avatar_url"),
    }
