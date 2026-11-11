"""SSO Provider 统一接口。每个 provider 实现 is_configured / authorize_url / exchange。"""
from urllib.parse import urlencode

import httpx


class SSOError(RuntimeError):
    pass


def _http() -> httpx.Client:
    return httpx.Client(timeout=10)


def build_authorize_url(endpoint: str, params: dict) -> str:
    return endpoint + "?" + urlencode(params)
