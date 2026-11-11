"""飞书（Feishu / Lark）OAuth。"""
from urllib.parse import urlencode

import httpx

from ...config import settings
from .base import SSOError, _http

AUTHORIZE = "https://open.feishu.cn/open-apis/authen/v1/authorize"
TOKEN = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
USER_INFO = "https://open.feishu.cn/open-apis/authen/v1/user_info"
NAME = "feishu"
LABEL = "飞书账号登录"


def is_configured() -> bool:
    return bool(settings.feishu_app_id and settings.feishu_app_secret)


def redirect_uri(request) -> str:
    if settings.feishu_redirect_uri:
        return settings.feishu_redirect_uri
    return str(request.base_url).rstrip("/") + "/api/auth/sso/feishu/callback"


def authorize_url(state: str, redirect_uri: str) -> str:
    return AUTHORIZE + "?" + urlencode({
        "app_id": settings.feishu_app_id,
        "redirect_uri": redirect_uri,
        "state": state,
    })


def exchange(code: str, redirect_uri: str) -> dict:
    """code 换 token 并取用户信息 → {subject, name, email, avatar}。"""
    with _http() as client:
        tok = client.post(TOKEN, data={
            "grant_type": "authorization_code",
            "client_id": settings.feishu_app_id,
            "client_secret": settings.feishu_app_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }).json()
        access = tok.get("access_token")
        if not access:
            raise SSOError(tok.get("msg") or tok.get("error_description") or "飞书 code 换 token 失败")
        info = client.get(USER_INFO, headers={"Authorization": "Bearer " + access}).json()
    d = info.get("data") or {}
    subject = d.get("open_id") or d.get("union_id")
    if not subject:
        raise SSOError("飞书未返回用户标识")
    return {
        "subject": subject,
        "name": d.get("name") or "飞书用户",
        "email": d.get("email"),
        "avatar": d.get("avatar_url"),
    }
