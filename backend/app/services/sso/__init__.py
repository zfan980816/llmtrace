"""SSO provider 注册表。新增 provider：实现三函数后在 PROVIDERS 注册即可。"""
from . import feishu, github, oidc
from .base import SSOError  # noqa: F401 (re-export)

PROVIDERS = {p.NAME: p for p in (feishu, oidc, github)}


def configured_providers() -> list[dict]:
    """返回已配置的 provider 列表（登录页按此渲染按钮）。"""
    return [{"name": p.NAME, "label": p.LABEL} for p in PROVIDERS.values() if p.is_configured()]


def get_provider(name: str):
    return PROVIDERS.get(name)
