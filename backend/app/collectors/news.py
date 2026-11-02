"""Local news portals: RSS feed for articles, optional CSS selectors for reader comments.

Without comment selectors each article (title + summary) becomes an item, which covers news about
city problems. With selectors, reader comments under each article are collected instead.
Respect each site's robots.txt and terms before enabling.
"""
import hashlib
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.collectors.base import Collector, CollectorError, RawItem

UA = "Mozilla/5.0 (compatible; PulseCityFeedback/1.0)"


def _entry_date(e) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        if e.get(key):
            return datetime(*e[key][:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        if e.get(key):
            try:
                return parsedate_to_datetime(e[key]).astimezone(timezone.utc)
            except (TypeError, ValueError):
                pass
    return datetime.now(timezone.utc)


def parse_feed(xml: str) -> list[RawItem]:
    feed = feedparser.parse(xml)
    out = []
    for e in feed.entries:
        link = e.get("link")
        title = (e.get("title") or "").strip()
        summary = BeautifulSoup(e.get("summary") or "", "lxml").get_text(" ", strip=True)
        text = f"{title}. {summary}".strip(". ") if summary else title
        if not text:
            continue
        ext = e.get("id") or link or hashlib.sha1(text.encode()).hexdigest()
        out.append(RawItem(external_id=str(ext)[:190], text=text, url=link, published_at=_entry_date(e),
                           author_id=None, platform="news", kind="article", extra={"kind": "article"}))
    return out


def parse_comments(html: str, url: str, sel: dict, article_text: str | None = None) -> list[RawItem]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for i, node in enumerate(soup.select(sel["comment"])):
        text_el = node.select_one(sel["text"]) if sel.get("text") else node
        text = text_el.get_text(" ", strip=True) if text_el else ""
        if not text:
            continue
        date = datetime.now(timezone.utc)
        if sel.get("date") and (d := node.select_one(sel["date"])):
            raw = d.get("datetime") or d.get_text(strip=True)
            try:
                date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        author = node.select_one(sel["author"]).get_text(strip=True) if sel.get("author") and node.select_one(sel["author"]) else None
        cid = node.get("id") or hashlib.sha1(f"{url}|{text}".encode()).hexdigest()[:16]
        out.append(RawItem(external_id=f"{url}#{cid}"[:190], text=text, url=url, published_at=date,
                           author_id=author, platform="news", kind="comment", parent_external_id=url,
                           parent_url=url, context_text=article_text, extra={"kind": "comment"}))
    return out


class NewsCollector(Collector):
    type = "news"
    title = "Новостной портал (RSS + комментарии)"
    description = "Статьи из RSS-ленты местного СМИ; при заданных CSS-селекторах — комментарии читателей."
    config_fields = [
        {"key": "feeds", "label": "RSS-ленты (URL через запятую)", "type": "list", "required": True},
        {"key": "comment_selector", "label": "CSS-селектор комментария (необязательно)", "type": "str"},
        {"key": "comment_text_selector", "label": "CSS-селектор текста комментария", "type": "str"},
        {"key": "comment_date_selector", "label": "CSS-селектор даты комментария", "type": "str"},
        {"key": "keywords", "label": "Брать только статьи с этими словами (через запятую)", "type": "list"},
        {"key": "max_articles", "label": "Статей за запуск", "type": "int", "default": 30},
    ]

    def fetch(self, since: datetime | None) -> list[RawItem]:
        feeds = [f.strip() for f in self.config.get("feeds", []) if f.strip()]
        if not feeds:
            raise CollectorError("Не указаны RSS-ленты")
        keywords = [k.lower().strip() for k in self.config.get("keywords", []) if k.strip()]
        sel = {"comment": self.config.get("comment_selector"), "text": self.config.get("comment_text_selector"),
               "date": self.config.get("comment_date_selector")}
        out: list[RawItem] = []
        # Regional feeds can be several hundred KB and slow to serve
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), headers={"User-Agent": UA}, follow_redirects=True) as client:
            for url in feeds:
                try:
                    r = client.get(url)
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    self.warnings.append(f"{url}: {e}")
                    continue
                articles = parse_feed(r.text)
                if keywords:
                    articles = [a for a in articles if any(k in a.text.lower() for k in keywords)]
                articles = [a for a in articles if not since or a.published_at >= since][: int(self.config.get("max_articles", 30))]
                if not sel["comment"]:
                    out.extend(articles)
                    continue
                for a in articles:
                    if not a.url:
                        continue
                    try:
                        page = client.get(a.url)
                        page.raise_for_status()
                        out.extend(parse_comments(page.text, a.url, sel, a.text[:1500]))
                    except httpx.HTTPError as e:
                        self.warnings.append(f"{a.url}: {e}")
                    time.sleep(0.5)
        if not out and self.warnings:
            raise CollectorError("; ".join(self.warnings[:5]))
        return out
