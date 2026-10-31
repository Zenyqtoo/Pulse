"""Direct messages to the akimat's Telegram bot (spec 3.7, Bot API long polling).

Long polling needs no public HTTPS URL. Messages are stored as is_direct=True: they go through the
same pipeline, but only operator/admin roles can read the original text and every read is audited.

Note: the spec's target is the akimat's OFFICIAL accounts. A bot created by the team is the
demonstration stream that 3.7.7 allows for the MVP; connecting the akimat's real bot is a token change.
"""
from datetime import datetime, timezone

import httpx

from app.collectors.base import Collector, CollectorError, RawItem
from app.config import get_settings

ACK_TEXT = ("Здравствуйте! Ваше обращение принято и будет передано в профильное подразделение акимата. "
            "Пожалуйста, не отправляйте в сообщениях ИИН и другие персональные данные без необходимости.")
START_TEXT = ("Это канал приёма обращений жителей. Опишите проблему: что случилось, где (улица, дом, микрорайон) "
              "и с какого времени. Ответ придёт после рассмотрения оператором.")


def api(token: str, method: str, **params):
    r = httpx.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=40)
    data = r.json()
    if not data.get("ok"):
        raise CollectorError(f"Bot API {method}: {data.get('description', r.status_code)}")
    return data["result"]


def send_message(chat_id: int | str, text: str, token: str | None = None) -> None:
    token = token or get_settings().telegram_bot_token
    if not token:
        raise CollectorError("TELEGRAM_BOT_TOKEN не задан")
    api(token, "sendMessage", chat_id=chat_id, text=text)


def updates_to_items(updates: list[dict]) -> tuple[list[RawItem], int | None, list[int]]:
    """Pure function (unit-tested): Bot API updates → RawItems, next offset, chats to greet."""
    items, greet = [], []
    next_offset = None
    for u in updates:
        next_offset = u["update_id"] + 1
        msg = u.get("message") or u.get("edited_message")
        if not msg or msg.get("chat", {}).get("type") != "private":
            continue
        text = msg.get("text") or msg.get("caption")
        if not text:
            continue
        if text.strip().startswith("/start"):
            greet.append(msg["chat"]["id"])
            continue
        items.append(RawItem(
            external_id=f"{msg['chat']['id']}:{msg['message_id']}",
            text=text,
            published_at=datetime.fromtimestamp(msg["date"], tz=timezone.utc),
            author_id=str(msg.get("from", {}).get("id")),
            platform="telegram_bot",
            is_direct=True, kind="message",
            extra={"reply_ref": {"kind": "telegram", "chat_id": msg["chat"]["id"], "message_id": msg["message_id"]}},
        ))
    return items, next_offset, greet


class TelegramBotCollector(Collector):
    type = "telegram_bot"
    title = "Direct: Telegram-бот приёма обращений"
    description = "Личные сообщения жителей в бот акимата (Bot API). Токен — TELEGRAM_BOT_TOKEN в .env."
    config_fields = [
        {"key": "auto_ack", "label": "Автоподтверждение получения (3.7.5)", "type": "bool", "default": True},
    ]
    state: dict

    def fetch(self, since: datetime | None) -> list[RawItem]:
        token = get_settings().telegram_bot_token
        if not token:
            raise CollectorError("TELEGRAM_BOT_TOKEN не задан в .env")
        offset = (getattr(self, "state", None) or {}).get("offset")
        updates = api(token, "getUpdates", offset=offset, timeout=0, allowed_updates=["message", "edited_message"])
        items, next_offset, greet = updates_to_items(updates)
        if next_offset is not None:
            self.state = {"offset": next_offset}
        for chat_id in greet:
            try:
                send_message(chat_id, START_TEXT, token)
            except Exception as e:
                self.warnings.append(f"greet: {e}")
        if self.config.get("auto_ack", True):
            for it in items:
                try:
                    send_message(it.extra["reply_ref"]["chat_id"], ACK_TEXT, token)
                except Exception as e:
                    self.warnings.append(f"ack: {e}")
        return items
