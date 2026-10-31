from app.collectors.base import Collector
from app.collectors.demo import DemoCollector
from app.collectors.instagram import InstagramCollector
from app.collectors.news import NewsCollector
from app.collectors.telegram_bot import TelegramBotCollector
from app.collectors.telegram_web import TelegramWebCollector
from app.collectors.telethon_comments import TelethonCollector
from app.collectors.threads import ThreadsCollector

COLLECTORS: dict[str, type[Collector]] = {
    c.type: c for c in [TelegramWebCollector, TelethonCollector, InstagramCollector, ThreadsCollector, NewsCollector,
                        TelegramBotCollector, DemoCollector]
}

# Sources that are not fetched by the scheduler
PASSIVE_TYPES = {"upload"}

PLATFORM_OF = {"telegram_web": "telegram", "telethon": "telegram", "instagram": "instagram", "threads": "threads",
               "news": "news", "telegram_bot": "direct", "upload": "upload", "demo": "demo"}
PLATFORM_NAMES = {"telegram": "Telegram", "instagram": "Instagram", "threads": "Threads", "news": "Новости и RSS",
                  "direct": "Direct (обращения)", "upload": "Загрузки", "demo": "Демо-набор", "other": "Другое"}


def describe() -> list[dict]:
    out = [{"type": c.type, "title": c.title, "description": c.description, "fields": c.config_fields,
            "platform": PLATFORM_OF.get(c.type, "other")} for c in COLLECTORS.values()]
    out.append({"type": "upload", "title": "Загрузка файлов CSV/XLSX",
                "description": "Ручная загрузка выгрузок (3.1.4)", "fields": [], "platform": "upload"})
    return out
