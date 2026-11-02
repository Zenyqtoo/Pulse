"""Reader comments on pavon.kz («Павлодар онлайн»), the city news site.

Comments are public (no login is needed to read them) and robots.txt allows these pages. They are not in the
HTML markup: each article page embeds them as JSON in #comment-wrapper-data, with the date written as
«15 октября 1:41» (no year). The year comes from the article's datePublished: a comment is never older than
its article. Quoted text (<blockquote>) is dropped so a reader is never credited with words they quoted.
Articles are found through the site's «latest comments» block plus the newest article ids on the home page.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.collectors.base import Collector, CollectorError, RawItem

BASE = "https://pavon.kz"
UA = "Mozilla/5.0 (compatible; PulseCityFeedback/1.0)"
CITY_TZ = timezone(timedelta(hours=5))
MONTHS = {m: i for i, m in enumerate(["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
                                      "сентября", "октября", "ноября", "декабря"], 1)}
_TIME = re.compile(r"(\d{1,2})\s+([а-я]+)\s+(?:(\d{4})\s+)?(\d{1,2}):(\d{2})")


def comment_date(raw: str, article_date: datetime) -> datetime | None:
    """«15 октября  1:41 Четверг» → aware datetime; the year is the first one not earlier than the article."""
    m = _TIME.search(raw.lower())
    if not m or m.group(2) not in MONTHS:
        return None
    day, month, year, hh, mm = int(m.group(1)), MONTHS[m.group(2)], m.group(3), int(m.group(4)), int(m.group(5))
    local = article_date.astimezone(CITY_TZ)
    dt = datetime(int(year) if year else local.year, month, day, hh, mm, tzinfo=CITY_TZ)
    if not year and dt < local - timedelta(minutes=1):
        dt = dt.replace(year=dt.year + 1)
    return dt.astimezone(timezone.utc)


def _text(body_html: str) -> str:
    soup = BeautifulSoup(body_html or "", "lxml")
    for q in soup.select("blockquote, .media-count"):
        q.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def parse_article(html: str, post_url: str) -> tuple[list[RawItem], int]:
    """Comments of one article page and the number of comment pages."""
    soup = BeautifulSoup(html, "lxml")
    data_el = soup.select_one("#comment-wrapper-data")
    date_el = soup.select_one("meta[itemprop=datePublished]")
    if not data_el or not date_el:
        return [], 0
    data = json.loads(data_el.string or "{}")
    article_date = datetime.fromisoformat(date_el["content"])
    title_el = soup.select_one("meta[property='og:title']") or soup.select_one("h1")
    title = (title_el.get("content") if title_el and title_el.name == "meta" else
             title_el.get_text(" ", strip=True) if title_el else "")
    lead_el = soup.select_one("meta[property='og:description']") or soup.select_one("meta[name=description]")
    context = ". ".join(x for x in [title, lead_el.get("content", "") if lead_el else ""] if x)[:1500]
    out = []
    for c in data.get("comments") or []:
        text = _text(c.get("body", ""))
        when = comment_date(c.get("time", ""), article_date)
        if not text or when is None:
            continue
        out.append(RawItem(
            external_id=f"pavon:{c['id']}", text=text, published_at=when, url=post_url,
            author_id=str(c.get("creator") or "") or None, platform="news",
            reactions=int(c.get("like_count") or 0), kind="reply" if c.get("replyto") else "comment",
            parent_external_id=post_url, parent_url=post_url, context_text=context,
            extra={"kind": "comment", "site": "pavon.kz", "article_title": title,
                   "article_published_at": article_date.isoformat()}))
    return out, int((data.get("pagination") or {}).get("total_pages") or 1)


def discover(html: str) -> list[int]:
    """Article ids from a pavon.kz page: the «latest comments» block first, then any article links."""
    soup = BeautifulSoup(html, "lxml")
    discussed = [a.get("href", "") for a in soup.select(".comment-context-item a.post-link")]
    rest = re.findall(r"/post/view/(\d+)", html)
    ids = [int(m.group(1)) for h in discussed if (m := re.search(r"/post/view/(\d+)", h))] + [int(x) for x in rest]
    return list(dict.fromkeys(ids))


class PavonCommentsCollector(Collector):
    type = "pavon_comments"
    title = "pavon.kz: комментарии читателей"
    description = ("Публичные комментарии под статьями «Павлодар онлайн» (pavon.kz). Вход не нужен; "
                   "дата берётся из страницы, ссылка ведёт на статью с комментарием.")
    config_fields = [
        {"key": "max_articles", "label": "Статей за запуск (до 10, пауза от 60 секунд)", "type": "int", "default": 8},
        {"key": "days", "label": "Глубина первого сбора, дней", "type": "int", "default": 180},
        {"key": "posts", "label": "Дополнительные id статей", "type": "list"},
    ]

    def fetch(self, since: datetime | None) -> list[RawItem]:
        floor = since or datetime.now(timezone.utc) - timedelta(days=int(self.config.get("days", 180)))
        out: list[RawItem] = []
        with httpx.Client(timeout=httpx.Timeout(40, connect=15), headers={"User-Agent": UA},
                          follow_redirects=False) as client:
            try:
                robots = client.get(BASE + "/robots.txt")
                robots.raise_for_status()
                rules = RobotFileParser()
                rules.parse(robots.text.splitlines())
                delay = max(60, rules.crawl_delay(UA) or rules.crawl_delay("*") or 0)

                def get(url):
                    if not rules.can_fetch(UA, url):
                        raise CollectorError("robots.txt запрещает выбранную страницу pavon.kz")
                    time.sleep(delay)
                    response = client.get(url)
                    response.raise_for_status()
                    return response

                home = get(BASE + "/")
            except httpx.HTTPError as e:
                raise CollectorError(f"pavon.kz недоступен: {e}") from e
            extra = [int(x) for x in self.config.get("posts", []) if str(x).strip().isdigit()]
            ids = list(dict.fromkeys(extra + discover(home.text)))[: max(1, min(10, int(self.config.get("max_articles", 8))))]
            for pid in ids:
                url = f"{BASE}/post/view/{pid}"
                try:
                    r = get(url)
                    if r.status_code == 404:
                        continue
                    r.raise_for_status()
                    items, pages = parse_article(r.text, url)
                    for page in range(2, min(pages, 10) + 1):
                        more = get(f"{url}?cpage={page}")
                        more.raise_for_status()
                        items += parse_article(more.text, url)[0]
                    out.extend(i for i in items if i.published_at >= floor)
                except (httpx.HTTPError, ValueError) as e:
                    self.warnings.append(f"{url}: {type(e).__name__}: {e}")
        if not out and self.warnings:
            raise CollectorError("; ".join(self.warnings[:5]))
        return out
