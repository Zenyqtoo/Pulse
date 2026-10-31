"""Instagram via Meta's official Instagram Platform API.

What the API allows (verified against developers.facebook.com, Oct 2026):
- own_media: comments and replies on posts of the CONNECTED professional account (e.g. the akimat's
  @pavlodar_akimdigi once the akimat connects it). Permissions: instagram_business_basic +
  instagram_business_manage_comments (Instagram Login) or instagram_basic + instagram_manage_comments +
  pages_read_engagement (Facebook Login).
- business_accounts: public posts (caption, link, counts) of OTHER professional accounts via Business
  Discovery. Their comments are NOT available through the API.
- hashtags: recent public posts with a hashtag. Requires App Review for "Instagram Public Content Access"
  and a Facebook Login token (INSTAGRAM_API_HOST=graph.facebook.com). Limit: 30 unique hashtags per 7 days.
- direct: messages people send to the connected account (instagram_business_manage_messages). Without
  Advanced Access (App Review) Meta only returns messages from people with a role on the app.
There is no official way to read arbitrary public comments or private accounts; this collector does not try.
"""
from datetime import datetime, timedelta, timezone

from app.collectors.base import Collector, CollectorError, RawItem
from app.config import get_settings
from app.integrations import meta_http
from app.integrations.meta_http import MetaError

MEDIA_FIELDS = "id,caption,permalink,timestamp,comments_count,like_count,media_type"
COMMENT_FIELDS = "id,text,timestamp,like_count,from{id,username},replies{id,text,timestamp,like_count,from{id,username}}"


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00").replace("+0000", "+00:00"))


class InstagramCollector(Collector):
    type = "instagram"
    title = "Instagram (официальный API Meta)"
    description = ("Комментарии и ответы под постами подключённого профессионального аккаунта, публичные посты "
                   "других бизнес-аккаунтов, хэштеги (после App Review) и Direct подключённого аккаунта.")
    config_fields = [
        {"key": "own_media", "label": "Комментарии и ответы под постами подключённого аккаунта", "type": "bool", "default": True},
        {"key": "business_accounts", "label": "Публичные бизнес-аккаунты (username, через запятую): только посты", "type": "list"},
        {"key": "hashtags", "label": "Хэштеги без # (нужен App Review: Instagram Public Content Access)", "type": "list"},
        {"key": "direct", "label": "Direct подключённого аккаунта (instagram_business_manage_messages)", "type": "bool", "default": False},
        {"key": "days", "label": "Глубина, дней", "type": "int", "default": 14},
        {"key": "max_posts", "label": "Постов за запуск", "type": "int", "default": 25},
    ]
    needs_credentials = "instagram"
    credential = None

    def _base(self) -> str:
        s = get_settings()
        return f"https://{s.instagram_api_host}/{s.meta_graph_version}"

    def fetch(self, since: datetime | None) -> list[RawItem]:
        cred = self.credential
        if cred is None:
            raise CollectorError("Instagram не подключён: нажмите «Подключить Instagram» на странице источников "
                                 "или задайте INSTAGRAM_ACCESS_TOKEN в .env")
        days = int(self.config.get("days", 14))
        floor = max(since, datetime.now(timezone.utc) - timedelta(days=days)) if since else \
            datetime.now(timezone.utc) - timedelta(days=days)
        out: list[RawItem] = []
        token = {"access_token": cred.access_token}
        with meta_http.client() as c:
            user = cred.user_id or "me"
            steps = []
            if self.config.get("own_media", True):
                steps.append(("комментарии своих постов", lambda: self._own_media(c, user, token, floor)))
            for name in [u.strip().lstrip("@") for u in self.config.get("business_accounts", []) if u.strip()]:
                steps.append((f"бизнес-аккаунт @{name}", lambda n=name: self._business(c, user, token, n, floor)))
            for tag in [t.strip().lstrip("#") for t in self.config.get("hashtags", []) if t.strip()]:
                steps.append((f"хэштег #{tag}", lambda t=tag: self._hashtag(c, user, token, t, floor)))
            if self.config.get("direct"):
                steps.append(("Direct", lambda: self._direct(c, user, token, floor)))
            if not steps:
                raise CollectorError("Не выбрано ни одного режима сбора")
            for label, step in steps:
                try:
                    out.extend(step())
                except MetaError as e:
                    self.warnings.append(f"{label}: {e}")
                    if e.code == 190 or e.is_rate_limit:
                        break
        if not out and self.warnings and len(self.warnings) == len(steps):
            raise CollectorError("; ".join(self.warnings))
        return out

    def _own_media(self, c, user, token, floor) -> list[RawItem]:
        base = self._base()
        out = []
        for m in meta_http.paged(c, f"{base}/{user}/media", {**token, "fields": MEDIA_FIELDS, "limit": 25},
                                 max_items=int(self.config.get("max_posts", 25))):
            if not m.get("comments_count"):
                continue
            data = meta_http.get(c, f"{base}/{m['id']}/comments", {**token, "fields": COMMENT_FIELDS})
            out.extend(self.comments_to_items(m, data.get("data", []), floor))
        return out

    @staticmethod
    def comments_to_items(media: dict, comments: list[dict], floor: datetime) -> list[RawItem]:
        """Pure mapping (unit-tested): one media's comments + nested replies → RawItems."""
        out = []
        caption = (media.get("caption") or "")[:1500]
        for cm in comments:
            items = [(cm, "comment", f"ig:{media['id']}")] + [
                (r, "reply", f"ig:{cm['id']}") for r in (cm.get("replies") or {}).get("data", [])]
            for row, kind, parent in items:
                if not row.get("text"):
                    continue
                ts = _ts(row["timestamp"])
                if ts < floor:
                    continue
                out.append(RawItem(
                    external_id=f"ig:{row['id']}", text=row["text"], published_at=ts, url=media.get("permalink"),
                    author_id=(row.get("from") or {}).get("id") or (row.get("from") or {}).get("username"),
                    platform="instagram", reactions=row.get("like_count", 0) or 0, kind=kind,
                    parent_external_id=parent, parent_url=media.get("permalink"), context_text=caption or None,
                ))
        return out

    def _business(self, c, user, token, name, floor) -> list[RawItem]:
        fields = f"business_discovery.username({name}){{username,media.limit(25){{{MEDIA_FIELDS}}}}}"
        data = meta_http.get(c, f"{self._base()}/{user}", {**token, "fields": fields})
        media = ((data.get("business_discovery") or {}).get("media") or {}).get("data", [])
        return [it for it in (self.media_to_item(m, f"@{name}") for m in media) if it and it.published_at >= floor]

    @staticmethod
    def media_to_item(m: dict, origin: str) -> RawItem | None:
        if not m.get("caption"):
            return None
        return RawItem(external_id=f"ig:{m['id']}", text=m["caption"], published_at=_ts(m["timestamp"]),
                       url=m.get("permalink"), author_id=origin, platform="instagram",
                       reactions=m.get("like_count", 0) or 0, replies=m.get("comments_count", 0) or 0, kind="post")

    def _hashtag(self, c, user, token, tag, floor) -> list[RawItem]:
        if user == "me":
            raise MetaError("для поиска по хэштегам укажите INSTAGRAM_USER_ID и токен Facebook Login")
        base = self._base()
        found = meta_http.get(c, f"{base}/ig_hashtag_search", {**token, "user_id": user, "q": tag})
        if not found.get("data"):
            return []
        tag_id = found["data"][0]["id"]
        media = meta_http.get(c, f"{base}/{tag_id}/recent_media", {**token, "user_id": user, "fields": MEDIA_FIELDS, "limit": 50})
        return [it for it in (self.media_to_item(m, f"#{tag}") for m in media.get("data", [])) if it and it.published_at >= floor]

    def _direct(self, c, user, token, floor) -> list[RawItem]:
        base = self._base()
        me = meta_http.get(c, f"{base}/me", {**token, "fields": "user_id,username"})
        own_ids = {str(me.get("id")), str(me.get("user_id"))}
        out = []
        convs = meta_http.get(c, f"{base}/{user}/conversations", {**token, "platform": "instagram", "fields": "id,updated_time"})
        for conv in convs.get("data", [])[:50]:
            if conv.get("updated_time") and _ts(conv["updated_time"]) < floor:
                continue
            detail = meta_http.get(c, f"{base}/{conv['id']}", {**token, "fields": "messages{id,message,from,created_time}"})
            for msg in (detail.get("messages") or {}).get("data", []):
                sender = msg.get("from") or {}
                if str(sender.get("id")) in own_ids or not msg.get("message"):
                    continue
                ts = _ts(msg["created_time"])
                if ts < floor:
                    continue
                out.append(RawItem(external_id=f"igdm:{msg['id']}", text=msg["message"], published_at=ts,
                                   author_id=sender.get("id"), platform="instagram", is_direct=True, kind="message",
                                   parent_external_id=f"igconv:{conv['id']}"))
        return out
