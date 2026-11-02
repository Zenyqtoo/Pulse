"""Bounded public HTML news collection; articles never become resident complaints."""
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.collectors.base import Collector, CollectorError, RawItem

CITY_TZ = timezone(timedelta(hours=5))
HOSTS = {"gorodpavlodar.kz": ("/News_2.html", 3), "obozrenie.kz": ("/", 3)}
UA = "CityAlertPublicResearch/1.0"


def article_url(url: str) -> bool:
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc not in HOSTS or p.query or p.fragment:
        return False
    return bool(re.fullmatch(r"/News_\d+_2\.html", p.path) if p.netloc == "gorodpavlodar.kz"
                else re.fullmatch(r"/\d+-[^/]+\.html", p.path))


def discover(html: str, base: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = [urljoin(base, a.get("href", "")) for a in soup.select("a[href]")]
    return list(dict.fromkeys(u for u in links if article_url(u) and urlsplit(u).netloc == urlsplit(base).netloc))


def parse_article(html: str, url: str) -> RawItem | None:
    """Keep a short excerpt and the actual publication date. Never invent a date."""
    if not article_url(url):
        return None
    s = BeautifulSoup(html, "lxml")
    host = urlsplit(url).netloc
    if host == "gorodpavlodar.kz":
        title = s.select_one("h2.title_news")
        date_node = title.select_one("small") if title else None
        match = re.search(r"(\d{2}\.\d{2}\.\d{4}),\s*(\d{2}:\d{2})", date_node.get_text() if date_node else "")
        if title is None or not match:
            return None
        when = datetime.strptime(" ".join(match.groups()), "%d.%m.%Y %H:%M")
        date_node.decompose()
        candidates = title.parent.find_all("div", recursive=False)
        candidates = [n for n in candidates if "display:none" not in n.get("style", "").replace(" ", "")]
        body = max(candidates, key=lambda n: len(n.get_text()), default=None)
    else:
        entry = s.select_one("#dle-content > section.entry-box.standard-post")
        title = entry.select_one(".entry-title") if entry else None
        thumb = entry.select_one(".entry-thumb") if entry else None
        match = re.search(r"(\d{1,2}-\d{1,2}-\d{4}),\s*(\d{2}:\d{2})", thumb.get_text() if thumb else "")
        if title is None or not match:
            return None
        when = datetime.strptime(" ".join(match.groups()), "%d-%m-%Y %H:%M")
        body = entry.select_one(".entry-content")
    if body is None:
        return None
    for node in body.select("script, style, form, .advertisement"):
        node.decompose()
    excerpt = re.sub(r"\s+", " ", body.get_text(" ", strip=True)).strip()
    heading = title.get_text(" ", strip=True)
    if not heading or len(excerpt) < 30:
        return None
    return RawItem(external_id=urlsplit(url).path, text=f"{heading}. {excerpt[:900]}",
                   url=url, published_at=when.replace(tzinfo=CITY_TZ).astimezone(timezone.utc),
                   platform="news", kind="article")


class CityWebCollector(Collector):
    type = "city_web"
    title = "Павлодар: публичные статьи сайтов"
    description = "gorodpavlodar.kz и obozrenie.kz: заголовок, короткий фрагмент, дата и ссылка. Это публикации СМИ, не обращения жителей."
    config_fields = [
        {"key": "host", "label": "Сайт (gorodpavlodar.kz или obozrenie.kz)", "type": "str", "required": True},
        {"key": "max_articles", "label": "Статей за запуск (до 20)", "type": "int", "default": 8},
        {"key": "articles", "label": "Конкретные URL статей (необязательно)", "type": "list"},
    ]

    def fetch(self, since: datetime | None) -> list[RawItem]:
        host = self.config.get("host", "")
        if host not in HOSTS:
            raise CollectorError("Разрешены только gorodpavlodar.kz и obozrenie.kz")
        base = f"https://{host}"
        limit = max(1, min(20, int(self.config.get("max_articles", 8))))
        with httpx.Client(timeout=40, follow_redirects=False, headers={"User-Agent": UA}) as client:
            robots = client.get(base + "/robots.txt")
            if robots.status_code != 200:
                raise CollectorError("Не удалось проверить robots.txt: сбор остановлен")
            rules = RobotFileParser()
            rules.parse(robots.text.splitlines())
            delay = max(HOSTS[host][1], rules.crawl_delay(UA) or rules.crawl_delay("*") or 0)

            def get(url: str) -> str:
                if urlsplit(url).netloc != host or not rules.can_fetch(UA, url):
                    raise CollectorError("robots.txt запрещает выбранную страницу")
                time.sleep(delay)
                r = client.get(url)
                r.raise_for_status()
                return r.text

            manual = self.config.get("articles") or []
            if isinstance(manual, str):
                manual = [u.strip() for u in manual.split(",") if u.strip()]
            if any(not article_url(u) or urlsplit(u).netloc != host for u in manual):
                raise CollectorError("Недопустимый URL статьи")
            urls = list(dict.fromkeys(manual or discover(get(base + HOSTS[host][0]), base)))[:limit]
            out = []
            for url in urls:
                try:
                    item = parse_article(get(url), url)
                    if item and (since is None or item.published_at >= since):
                        out.append(item)
                    elif item is None:
                        self.warnings.append(f"{url}: не найдены текст или дата; запись пропущена")
                except (httpx.HTTPError, ValueError, CollectorError) as exc:
                    self.warnings.append(f"{url}: {type(exc).__name__}")
            if not out and self.warnings:
                raise CollectorError("; ".join(self.warnings[:3]))
            return out
