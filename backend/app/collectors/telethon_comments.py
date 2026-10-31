"""Comments under public channel posts and messages in public city chats, via the official
Telegram client API (Telethon).

Needs TELEGRAM_API_ID / TELEGRAM_API_HASH from my.telegram.org and a one-time login:
    python -m app.cli telethon-login
Reads only what any Telegram user can see without joining private chats.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.collectors.base import Collector, CollectorError, RawItem
from app.config import get_settings


def _reactions(msg) -> int:
    r = getattr(msg, "reactions", None)
    if not r or not getattr(r, "results", None):
        return 0
    return sum(getattr(x, "count", 0) for x in r.results)


def comment_item(ch: str, post_id: int, post_text: str, c) -> RawItem:
    """A comment in a channel's discussion thread. Replies to other comments keep their parent (unit-tested)."""
    reply_to = getattr(c, "reply_to", None)
    parent_msg = getattr(reply_to, "reply_to_msg_id", None)
    top = getattr(reply_to, "reply_to_top_id", None)
    is_nested = bool(top and parent_msg and parent_msg != top)
    return RawItem(
        external_id=f"{ch}/{post_id}/c{c.id}", text=c.message, published_at=c.date,
        url=f"https://t.me/{ch}/{post_id}?comment={c.id}", author_id=str(c.sender_id), platform="telegram",
        reactions=_reactions(c), replies=getattr(getattr(c, "replies", None), "replies", 0) or 0,
        kind="reply" if is_nested else "comment",
        parent_external_id=f"{ch}/{post_id}/c{parent_msg}" if is_nested else f"{ch}/{post_id}",
        parent_url=f"https://t.me/{ch}/{post_id}", context_text=post_text[:1500] or None,
    )


class TelethonCollector(Collector):
    type = "telethon"
    title = "Telegram: комментарии и публичные чаты (Telethon)"
    description = ("Комментарии под постами публичных каналов и сообщения публичных городских чатов. "
                   "Нужны TELEGRAM_API_ID/HASH и однократный вход: python -m app.cli telethon-login")
    config_fields = [
        {"key": "channels", "label": "Каналы с комментариями (username)", "type": "list"},
        {"key": "chats", "label": "Публичные чаты (username)", "type": "list"},
        {"key": "days", "label": "Глубина, дней", "type": "int", "default": 7},
        {"key": "posts_per_channel", "label": "Постов на канал", "type": "int", "default": 30},
        {"key": "include_posts", "label": "Собирать и сами посты канала", "type": "bool", "default": False},
    ]

    def fetch(self, since: datetime | None) -> list[RawItem]:
        s = get_settings()
        if not s.telegram_api_id or not s.telegram_api_hash:
            raise CollectorError("Не заданы TELEGRAM_API_ID и TELEGRAM_API_HASH в .env")
        try:
            return asyncio.run(self._fetch(since))
        except CollectorError:
            raise
        except Exception as e:
            raise CollectorError(f"Telethon: {type(e).__name__}: {e}") from e

    async def _fetch(self, since: datetime | None) -> list[RawItem]:
        from telethon import TelegramClient
        from telethon.errors import FloodWaitError

        s = get_settings()
        days = int(self.config.get("days", 7))
        floor = since or (datetime.now(timezone.utc) - timedelta(days=days))
        out: list[RawItem] = []
        client = TelegramClient(s.telegram_session_path, s.telegram_api_id, s.telegram_api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise CollectorError("Сессия Telethon не авторизована: выполните python -m app.cli telethon-login")
            for ch in [c.strip().lstrip("@") for c in self.config.get("channels", []) if c.strip()]:
                try:
                    async for post in client.iter_messages(ch, limit=int(self.config.get("posts_per_channel", 30))):
                        if post.date < floor:
                            break
                        post_url = f"https://t.me/{ch}/{post.id}"
                        if self.config.get("include_posts") and post.message:
                            out.append(RawItem(external_id=f"{ch}/{post.id}", text=post.message, published_at=post.date,
                                               url=post_url, author_id=ch, platform="telegram", views=post.views or 0,
                                               reactions=_reactions(post), kind="post",
                                               replies=getattr(post.replies, "replies", 0) if post.replies else 0))
                        if not post.replies or not post.replies.replies:
                            continue
                        async for c in client.iter_messages(ch, reply_to=post.id, limit=300):
                            if not c.message or c.date < floor:
                                continue
                            out.append(comment_item(ch, post.id, post.message or "", c))
                except FloodWaitError as e:
                    self.warnings.append(f"{ch}: FloodWait {e.seconds} c — остановлено")
                    break
                except Exception as e:
                    self.warnings.append(f"{ch}: {type(e).__name__}: {e}")
            state = getattr(self, "state", None) or {}
            min_ids = state.setdefault("chat_min_id", {})
            for chat in [c.strip().lstrip("@") for c in self.config.get("chats", []) if c.strip()]:
                try:
                    newest = int(min_ids.get(chat, 0))
                    async for m in client.iter_messages(chat, limit=500, min_id=int(min_ids.get(chat, 0))):
                        if m.date < floor:
                            break
                        newest = max(newest, m.id)
                        if not m.message:
                            continue
                        reply_to = getattr(getattr(m, "reply_to", None), "reply_to_msg_id", None)
                        out.append(RawItem(
                            external_id=f"{chat}/{m.id}", text=m.message, published_at=m.date,
                            url=f"https://t.me/{chat}/{m.id}", author_id=str(m.sender_id), platform="telegram",
                            reactions=_reactions(m), kind="reply" if reply_to else "post",
                            parent_external_id=f"{chat}/{reply_to}" if reply_to else None,
                        ))
                    min_ids[chat] = newest
                except Exception as e:
                    self.warnings.append(f"{chat}: {type(e).__name__}: {e}")
            self.state = state
        finally:
            await client.disconnect()
        if not out and self.warnings:
            raise CollectorError("; ".join(self.warnings))
        return out
