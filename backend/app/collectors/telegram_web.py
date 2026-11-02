"""Public Telegram channels via the official web preview https://t.me/s/<channel>.

No login or API key. The preview shows posts with text, date and views; comments are not
included there (see the Telethon collector for those). Only channels with a public preview work.
"""
from html import unescape
import re
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from app.collectors.base import Collector, CollectorError, RawItem

UA = "Mozilla/5.0 (compatible; PulseCityFeedback/1.0; +public-data-monitoring)"


def _num(s: str | None) -> int:
    if not s:
        return 0
    s = s.strip().replace(",", ".").upper()
    mult = 1
    if s.endswith("K"):
        mult, s = 1000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def parse_page(html: str, channel: str) -> list[RawItem]:
    soup = BeautifulSoup(html, "lxml")
    out: list[RawItem] = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        post = msg["data-post"]  # "channel/123"
        text_el = msg.select_one(".tgme_widget_message_text")
        if text_el is None:
            continue
        for br in text_el.find_all("br"):
            br.replace_with("\n")
        # some channels publish already-escaped text ("&mdash;"), which BeautifulSoup leaves as is
        text = unescape(text_el.get_text("", strip=False)).strip()
        if not text:
            continue
        t = msg.select_one(".tgme_widget_message_date time[datetime]") or msg.select_one("time[datetime]")
        if t is None:
            continue
        published = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        views = _num(getattr(msg.select_one(".tgme_widget_message_views"), "text", None))
        reactions = sum(_num(r.get_text()) for r in msg.select(".tgme_reaction"))
        author_el = msg.select_one(".tgme_widget_message_from_author") or msg.select_one(".tgme_widget_message_owner_name")
        author = author_el.get_text(strip=True) if author_el else channel
        out.append(RawItem(
            external_id=post, text=text, published_at=published, url=f"https://t.me/{post}",
            author_id=author, platform="telegram", views=views, reactions=reactions,
        ))
    return out


def _post_id(item: RawItem) -> int:
    m = re.search(r"/(\d+)$", item.external_id)
    return int(m.group(1)) if m else 0


def _before_id(items: list[RawItem]) -> int | None:
    ids = [int(m.group(1)) for i in items if (m := re.search(r"/(\d+)$", i.external_id))]
    return min(ids) if ids else None


class TelegramWebCollector(Collector):
    type = "telegram_web"
    title = "Telegram: публичные каналы (t.me/s)"
    description = "Посты публичных каналов через официальный веб-просмотр Telegram. Без авторизации."
    config_fields = [
        {"key": "channels", "label": "Каналы (username без @, через запятую)", "type": "list", "required": True},
        {"key": "pages", "label": "Страниц истории на канал (≈20 постов)", "type": "int", "default": 3},
    ]

    def fetch(self, since: datetime | None) -> list[RawItem]:
        channels = [c.strip().lstrip("@").replace("https://t.me/", "") for c in self.config.get("channels", []) if c.strip()]
        if not channels:
            raise CollectorError("Не указаны каналы")
        pages = int(self.config.get("pages", 3))
        result: list[RawItem] = []
        errors = []
        state = getattr(self, "state", None) or {}
        last_ids: dict = state.setdefault("last_id", {})
        with httpx.Client(timeout=20, headers={"User-Agent": UA}, follow_redirects=True) as client:
            for ch in channels:
                before = None
                seen = int(last_ids.get(ch, 0))   # fixed for the whole run, so older pages are not mistaken for seen ones
                for _ in range(pages):
                    url = f"https://t.me/s/{ch}" + (f"?before={before}" if before else "")
                    try:
                        r = client.get(url)
                        r.raise_for_status()
                    except httpx.HTTPError as e:
                        errors.append(f"{ch}: {e}")
                        break
                    items = parse_page(r.text, ch)
                    if not items:
                        if before is None:
                            errors.append(f"{ch}: нет веб-просмотра или постов")
                        break
                    fresh = [i for i in items if _post_id(i) > seen]
                    result.extend(fresh)
                    newest = max(_post_id(i) for i in items)
                    last_ids[ch] = max(int(last_ids.get(ch, 0)), newest)
                    # incremental: stop once we reach posts collected in an earlier run
                    if len(fresh) < len(items) or (since and min(i.published_at for i in items) < since):
                        break
                    before = _before_id(items)
                    time.sleep(1.0)  # be polite
        if not result and errors:
            raise CollectorError("; ".join(errors))
        self.warnings.extend(errors)
        self.state = state
        return result
