"""Threads via Meta's official Threads API (graph.threads.com/v1.0).

What the API allows (verified against developers.facebook.com, Oct 2026):
- own_posts: posts of the connected account and all replies to them (/me/threads, /{id}/conversation).
  Permissions: threads_basic, threads_read_replies.
- keywords: GET /keyword_search (search_type=RECENT). Permission threads_keyword_search. Before Meta approves
  it, results cover ONLY the connected account's own posts; after approval, public posts. 2,200 queries per
  24 h per user. Sensitive keywords return nothing.
- profiles: GET /profile_posts?username= (threads_profile_discovery). With standard access only Meta's own
  accounts are returned; public profiles with ≥ 100 followers need advanced access.
- Replies to other users' public posts are fetched where Meta allows; otherwise a warning is logged.
Engagement counts (likes, views) require threads_manage_insights and are not collected.
"""
from datetime import datetime, timedelta, timezone

from app.collectors.base import Collector, CollectorError, RawItem
from app.config import get_settings
from app.integrations import meta_http
from app.integrations.meta_http import MetaError

POST_FIELDS = "id,text,permalink,timestamp,username,has_replies,is_reply,media_type"
REPLY_FIELDS = "id,text,permalink,timestamp,username,has_replies,is_reply,root_post,replied_to"


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00"))


def to_item(row: dict, context: str | None = None, root: dict | None = None) -> RawItem | None:
    """Pure mapping (unit-tested)."""
    if not row.get("text"):
        return None
    is_reply = bool(row.get("is_reply") or row.get("replied_to"))
    parent = (row.get("replied_to") or {}).get("id") or (root or {}).get("id")
    return RawItem(
        external_id=f"th:{row['id']}", text=row["text"], published_at=_ts(row["timestamp"]), url=row.get("permalink"),
        author_id=row.get("username"), platform="threads", kind="reply" if is_reply else "post",
        parent_external_id=f"th:{parent}" if is_reply and parent else None,
        parent_url=(root or {}).get("permalink"), context_text=context,
    )


class ThreadsCollector(Collector):
    type = "threads"
    title = "Threads (официальный API Meta)"
    description = ("Поиск публичных постов по ключевым словам (после одобрения threads_keyword_search), ответы "
                   "на посты, посты подключённого аккаунта и публичные профили (после одобрения profile discovery).")
    config_fields = [
        {"key": "keywords", "label": "Ключевые слова (через запятую)", "type": "list", "default": ["Павлодар"]},
        {"key": "own_posts", "label": "Посты подключённого аккаунта и ответы на них", "type": "bool", "default": True},
        {"key": "fetch_replies", "label": "Собирать ответы на найденные посты", "type": "bool", "default": True},
        {"key": "profiles", "label": "Публичные профили (username): нужен threads_profile_discovery", "type": "list"},
        {"key": "days", "label": "Глубина, дней", "type": "int", "default": 7},
        {"key": "max_per_keyword", "label": "Постов на ключевое слово", "type": "int", "default": 50},
    ]
    needs_credentials = "threads"
    credential = None

    def _base(self) -> str:
        return f"https://{get_settings().threads_api_host}/v1.0"

    def fetch(self, since: datetime | None) -> list[RawItem]:
        if self.credential is None:
            raise CollectorError("Threads не подключён: нажмите «Подключить Threads» на странице источников "
                                 "или задайте THREADS_ACCESS_TOKEN в .env")
        days = int(self.config.get("days", 7))
        floor = datetime.now(timezone.utc) - timedelta(days=days)
        if since and since > floor:
            floor = since
        token = {"access_token": self.credential.access_token}
        state = getattr(self, "state", None) or {}
        out: dict[str, RawItem] = {}
        self._replies_blocked = False
        with meta_http.client() as c:
            if self.config.get("own_posts", True):
                try:
                    for p in meta_http.paged(c, f"{self._base()}/me/threads",
                                             {**token, "fields": POST_FIELDS, "since": int(floor.timestamp()), "limit": 50},
                                             max_items=100):
                        if p.get("has_replies"):
                            for it in self._replies(c, token, p):
                                out[it.external_id] = it
                except MetaError as e:
                    self.warnings.append(f"свои посты: {e}")
            for kw in [k.strip() for k in self.config.get("keywords", []) if k.strip()]:
                last = state.get("kw", {}).get(kw)
                kw_since = max(floor, datetime.fromisoformat(last)) if last else floor
                try:
                    found = meta_http.get(c, f"{self._base()}/keyword_search", {
                        **token, "q": kw, "search_type": "RECENT", "fields": POST_FIELDS,
                        "since": int(kw_since.timestamp()), "limit": min(100, int(self.config.get("max_per_keyword", 50)))})
                except MetaError as e:
                    self.warnings.append(f"поиск «{kw}»: {e}")
                    if e.is_rate_limit or e.code == 190:
                        break
                    continue
                newest = kw_since
                for p in found.get("data", []):
                    it = to_item(p)
                    if it:
                        out[it.external_id] = it
                        newest = max(newest, it.published_at)
                    if p.get("has_replies") and self.config.get("fetch_replies", True):
                        for r in self._replies(c, token, p):
                            out[r.external_id] = r
                state.setdefault("kw", {})[kw] = newest.isoformat()
            for name in [u.strip().lstrip("@") for u in self.config.get("profiles", []) if u.strip()]:
                try:
                    data = meta_http.get(c, f"{self._base()}/profile_posts",
                                         {**token, "username": name, "fields": POST_FIELDS, "limit": 25})
                    for p in data.get("data", []):
                        it = to_item(p)
                        if it and it.published_at >= floor:
                            out[it.external_id] = it
                except MetaError as e:
                    self.warnings.append(f"профиль @{name}: {e}")
        self.state = state
        if not out and self.warnings:
            raise CollectorError("; ".join(self.warnings))
        return list(out.values())

    def _replies(self, c, token, post: dict) -> list[RawItem]:
        if self._replies_blocked:
            return []
        try:
            data = meta_http.get(c, f"{self._base()}/{post['id']}/conversation",
                                 {**token, "fields": REPLY_FIELDS, "reverse": "false"})
        except MetaError as e:
            if e.is_permission:
                self._replies_blocked = True
                self.warnings.append(f"ответы: {e} (нужно threads_read_replies или доступ к чужим постам)")
                return []
            raise
        return [it for it in (to_item(r, post.get("text"), post) for r in data.get("data", [])) if it]
