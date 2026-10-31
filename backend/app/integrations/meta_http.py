"""Minimal client for Meta Graph-style APIs (Instagram, Threads): errors, paging, rate limits."""
from collections.abc import Iterator

import httpx

from app.collectors.base import CollectorError

# Tests replace this with httpx.MockTransport
transport: httpx.BaseTransport | None = None

RATE_LIMIT_CODES = {4, 17, 32, 613, 80002, 80005, 80008}
PERMISSION_CODES = {10, 200, 190, 3, 100}


class MetaError(CollectorError):
    def __init__(self, message: str, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status

    @property
    def is_rate_limit(self) -> bool:
        return self.code in RATE_LIMIT_CODES

    @property
    def is_permission(self) -> bool:
        return self.code in PERMISSION_CODES or self.status in (401, 403)


def client() -> httpx.Client:
    return httpx.Client(timeout=30, transport=transport, follow_redirects=True)


def _raise(r: httpx.Response) -> None:
    try:
        err = r.json().get("error", {})
    except ValueError:
        err = {}
    code = err.get("code")
    msg = err.get("error_user_msg") or err.get("message") or f"HTTP {r.status_code}"
    if code == 190:
        msg = f"Токен недействителен или истёк — подключите аккаунт заново ({msg})"
    elif code in RATE_LIMIT_CODES:
        msg = f"Лимит запросов Meta исчерпан, сбор продолжится позже ({msg})"
    elif code in (10, 200) or r.status_code == 403:
        msg = f"Недостаточно разрешений для этого запроса ({msg})"
    raise MetaError(msg, code, r.status_code)


def get(c: httpx.Client, url: str, params: dict) -> dict:
    r = c.get(url, params=params)
    if r.status_code >= 400:
        _raise(r)
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        _raise(r)
    return data


def post(c: httpx.Client, url: str, data: dict) -> dict:
    r = c.post(url, data=data)
    if r.status_code >= 400:
        _raise(r)
    return r.json()


def paged(c: httpx.Client, url: str, params: dict, max_items: int = 500) -> Iterator[dict]:
    """Follows paging.next until max_items."""
    n = 0
    data = get(c, url, params)
    while True:
        for row in data.get("data", []):
            yield row
            n += 1
            if n >= max_items:
                return
        nxt = (data.get("paging") or {}).get("next")
        if not nxt:
            return
        r = c.get(nxt)
        if r.status_code >= 400:
            _raise(r)
        data = r.json()
