"""Pavlodar geo filter, Instagram/Threads collectors and OAuth (Meta APIs mocked at the HTTP layer),
improved Telegram collectors, cross-platform clustering, sources management."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app import geo, pipeline
from app.ai import llm
from app.collectors.base import CollectorError, RawItem
from app.collectors.instagram import InstagramCollector
from app.collectors.telegram_web import TelegramWebCollector
from app.collectors.telethon_comments import comment_item
from app.collectors.threads import ThreadsCollector, to_item
from app.integrations import meta_http, tokens
from app.integrations.tokens import Credential
from app.models import AppState, Cluster, ClusterItem, Item, Source

NOW = datetime.now(timezone.utc)
ISO = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S+0000")  # noqa: E731


# ---------------------------------------------------------------- geo classifier
@pytest.mark.parametrize("text,scope,expected", [
    ("В Павлодаре на Торайгырова огромные ямы", "national", "local"),
    ("Павлодарда жылу жоқ, балалар ауырып жатыр", "unknown", "local"),
    ("Pavlodar: no hot water in Usolsky district again", "national", "local"),
    ("Павлодарэнерго опять отключил свет в Усольском", "unknown", "local"),
    ("Когда починят дорогу на Ломова?", "city", "local"),
    ("Когда починят дорогу на Ломова?", "region", "possible"),
    ("В Павлодарской области ожидаются морозы", "region", "possible"),
    ("В Павлодаре и Экибастузе отключат воду", "region", "possible"),
    ("В Экибастузе третий день нет отопления", "region", "not_local"),
    ("Аксу: жители жалуются на пыль от ГРЭС", "region", "not_local"),
    ("В Астане снова пробки на Кабанбай батыра", "national", "not_local"),
    ("Опять нет горячей воды", "national", "not_local"),
])
def test_geo_rules(text, scope, expected):
    assert geo.classify_rules(text, scope).status == expected


def test_region_form_is_not_city():
    ev = geo.classify_rules("Аким Павлодарской области провёл совещание", "region").evidence
    assert not ev.get("city")


def test_other_place_is_certain_and_skips_llm():
    r = geo.classify_rules("В Майкаине нет воды", "region")
    assert r.certain and r.status == "not_local"
    assert geo.combine(r, "local", "x", "region").status == "not_local"


def test_comment_uses_parent_post_context():
    assert geo.classify_rules("И у нас так же уже неделю!", "national",
                              context="В Павлодаре на Ломова прорыв трубы").status == "local"


def test_llm_context_overrides_incidental_mention():
    r = geo.classify_rules("Иртыш Павлодар обыграл Кайрат 2:1", "national")
    assert r.status == "local"                     # keywords alone would say local
    final = geo.combine(r, "not_local", "спортивный результат, не жизнь города", "national")
    assert final.status == "not_local" and "ИИ" in final.reason


def test_llm_cannot_make_other_city_local():
    r = geo.classify_rules("На Ломова прорыв, а в Экибастузе тоже", "region")
    assert geo.combine(r, "local", "x", "region").status == "possible"


# ---------------------------------------------------------------- LLM geo field
class FakeLLM:
    def __init__(self, payload):
        self.payload, self.messages, self.seen = payload, self, []

    def create(self, **kw):
        self.seen.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="record_analysis", input=self.payload)])


def test_llm_receives_source_context_and_returns_geo(monkeypatch):
    from app.reference import DEPARTMENTS

    monkeypatch.setattr(llm.get_settings(), "anthropic_api_key", "test")
    fake = FakeLLM({"departments": ["roads"], "primary_department": "roads", "department_confidence": 0.9,
                    "sentiment": "negative", "sentiment_score": -0.6, "sentiment_confidence": 0.9,
                    "message_type": "complaint", "is_spam": False, "entities": {}, "urgency_markers": [],
                    "pii_names": [], "rationale": "Жалоба на дорогу.",
                    "geo": {"relevance": "local", "place": "Павлодар", "reason": "канал о Павлодаре"}})
    llm.set_client(fake)
    out = llm.enrich("Яма на Кутузова", DEPARTMENTS, context={"source": "Типичный Павлодар (telegram; посвящён городу)",
                                                             "parent_text": "Дороги города"})
    assert out.result.geo.relevance == "local"
    user_msg = fake.seen[0]["messages"][0]["content"]
    assert "Типичный Павлодар" in user_msg and "Дороги города" in user_msg
    assert "Павлодар" in fake.seen[0]["system"][0]["text"]
    assert "geo" in fake.seen[0]["tools"][0]["input_schema"]["required"]


# ---------------------------------------------------------------- Meta HTTP mocking
def mock_meta(routes: dict, calls: list):
    def handler(request: httpx.Request):
        calls.append(request)
        path = request.url.path
        for key, resp in routes.items():
            if path.endswith(key):
                status, body = resp(request) if callable(resp) else resp
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"error": {"message": f"no route {path}", "code": 100}})
    return httpx.MockTransport(handler)


@pytest.fixture
def meta(monkeypatch):
    calls: list = []

    def install(routes):
        monkeypatch.setattr(meta_http, "transport", mock_meta(routes, calls))
        return calls
    yield install
    meta_http.transport = None


IG_MEDIA = {"data": [
    {"id": "m1", "caption": "Ремонт дорог в Павлодаре продолжается", "permalink": "https://www.instagram.com/p/AAA/",
     "timestamp": ISO(NOW - timedelta(days=1)), "comments_count": 2, "like_count": 40},
    {"id": "m2", "caption": "Без комментариев", "permalink": "https://www.instagram.com/p/BBB/",
     "timestamp": ISO(NOW - timedelta(days=1)), "comments_count": 0, "like_count": 5},
]}
IG_COMMENTS = {"data": [
    {"id": "c1", "text": "А на Кутузова яма так и осталась!", "timestamp": ISO(NOW - timedelta(hours=5)), "like_count": 7,
     "from": {"id": "u1", "username": "resident1"},
     "replies": {"data": [{"id": "r1", "text": "Подтверждаю, пробил колесо", "timestamp": ISO(NOW - timedelta(hours=4)),
                           "like_count": 2, "from": {"id": "u2", "username": "resident2"}}]}},
    {"id": "c_old", "text": "старый", "timestamp": ISO(NOW - timedelta(days=60)), "from": {"id": "u3"}},
]}


def ig(config):
    c = InstagramCollector(config)
    c.credential = Credential("instagram", "TOKEN", "1784", "akimat", None, [], "oauth")
    return c


def test_instagram_comments_and_replies(meta):
    calls = meta({"/1784/media": (200, IG_MEDIA), "/m1/comments": (200, IG_COMMENTS)})
    items = ig({"own_media": True, "days": 14}).fetch(None)
    assert [i.external_id for i in items] == ["ig:c1", "ig:r1"]
    c1, r1 = items
    assert c1.kind == "comment" and c1.parent_external_id == "ig:m1" and c1.url == "https://www.instagram.com/p/AAA/"
    assert r1.kind == "reply" and r1.parent_external_id == "ig:c1" and c1.context_text.startswith("Ремонт дорог")
    assert c1.reactions == 7 and c1.author_id == "u1"
    assert not any("/m2/comments" in str(r.url) for r in calls)          # no comments → no call
    assert all(parse_qs(urlparse(str(r.url)).query)["access_token"] == ["TOKEN"] for r in calls)


def test_instagram_business_discovery_and_permission_warning(meta):
    bd = {"business_discovery": {"username": "pavlodar_akimdigi", "media": {"data": [
        {"id": "p9", "caption": "Акимат: график вывоза снега", "permalink": "https://www.instagram.com/p/CCC/",
         "timestamp": ISO(NOW - timedelta(days=2)), "comments_count": 12, "like_count": 80}]}}}
    meta({"/1784": (200, bd), "/ig_hashtag_search": (400, {"error": {"code": 10, "message": "Application does not have permission"}})})
    c = ig({"own_media": False, "business_accounts": ["pavlodar_akimdigi"], "hashtags": ["павлодар"]})
    items = c.fetch(None)
    assert len(items) == 1 and items[0].kind == "post" and items[0].replies == 12
    assert any("Недостаточно разрешений" in w for w in c.warnings)


def test_instagram_requires_connection():
    with pytest.raises(CollectorError, match="не подключён"):
        InstagramCollector({}).fetch(None)


def test_instagram_expired_token_stops(meta):
    meta({"/1784/media": (400, {"error": {"code": 190, "message": "Session expired"}})})
    with pytest.raises(CollectorError, match="Токен недействителен"):
        ig({"own_media": True}).fetch(None)


def test_threads_search_replies_and_incremental_state(meta):
    post = {"id": "t1", "text": "Павлодар, когда уберут снег на Естая?", "permalink": "https://www.threads.com/@a/post/X",
            "timestamp": ISO(NOW - timedelta(hours=3)), "username": "a", "has_replies": True, "is_reply": False}
    reply = {"id": "t2", "text": "На Естая вообще не чистят", "permalink": "https://www.threads.com/@b/post/Y",
             "timestamp": ISO(NOW - timedelta(hours=2)), "username": "b", "is_reply": True, "replied_to": {"id": "t1"},
             "root_post": {"id": "t1"}}
    calls = meta({"/keyword_search": (200, {"data": [post]}), "/t1/conversation": (200, {"data": [reply]})})
    c = ThreadsCollector({"keywords": ["Павлодар"], "own_posts": False, "fetch_replies": True})
    c.credential = Credential("threads", "TT", "9", "acc", None, [], "oauth")
    c.state = {}
    items = {i.external_id: i for i in c.fetch(None)}
    assert set(items) == {"th:t1", "th:t2"}
    assert items["th:t2"].kind == "reply" and items["th:t2"].parent_external_id == "th:t1"
    assert items["th:t2"].context_text.startswith("Павлодар, когда")
    q = parse_qs(urlparse(str(calls[0].url)).query)
    assert q["q"] == ["Павлодар"] and q["search_type"] == ["RECENT"]
    assert c.state["kw"]["Павлодар"]                                   # next run searches from here


def test_threads_replies_blocked_by_permission_is_reported(meta):
    post = {"id": "t1", "text": "Павлодар: опять пробки", "timestamp": ISO(NOW), "has_replies": True}
    meta({"/keyword_search": (200, {"data": [post]}),
          "/t1/conversation": (403, {"error": {"code": 10, "message": "permission"}})})
    c = ThreadsCollector({"keywords": ["Павлодар"], "own_posts": False})
    c.credential = Credential("threads", "TT", "9", "acc", None, [], "env")
    items = c.fetch(None)
    assert [i.external_id for i in items] == ["th:t1"]
    assert any("threads_read_replies" in w for w in c.warnings)


def test_threads_mapping_without_text_is_skipped():
    assert to_item({"id": "x", "timestamp": ISO(NOW)}) is None


# ---------------------------------------------------------------- OAuth + token storage
def test_token_encrypted_at_rest_and_never_returned(client, admin, db):
    tokens.save(db, "threads", "SECRET-TOKEN-123", "9", "pulse_acc", 5_000_000, ["threads_basic"])
    raw = json.dumps(db.get(AppState, "oauth:threads").value)
    assert "SECRET-TOKEN-123" not in raw
    assert tokens.load(db, "threads").access_token == "SECRET-TOKEN-123"
    st = client.get("/api/connect/status", headers=admin).json()
    assert "SECRET-TOKEN-123" not in json.dumps(st)
    th = next(x for x in st if x["platform"] == "threads")
    assert th["connected"] and th["username"] == "pulse_acc" and th["capabilities"]
    client.delete("/api/connect/threads", headers=admin)
    assert tokens.load(db, "threads") is None


def test_instagram_oauth_flow(client, admin, db, meta, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "instagram_app_id", "APPID")
    monkeypatch.setattr(s, "instagram_app_secret", "APPSECRET")
    start = client.get("/api/connect/instagram/start", headers=admin).json()["url"]
    q = parse_qs(urlparse(start).query)
    assert start.startswith("https://www.instagram.com/oauth/authorize") and q["client_id"] == ["APPID"]
    assert "instagram_business_manage_comments" in q["scope"][0]
    calls = meta({
        "/oauth/access_token": (200, {"data": [{"access_token": "SHORT", "user_id": "1784", "permissions": "instagram_business_basic"}]}),
        "/access_token": (200, {"access_token": "LONG", "token_type": "bearer", "expires_in": 5183944}),
        "/me": (200, {"user_id": "1784", "username": "pavlodar_test"}),
    })
    r = client.get("/api/connect/instagram/callback", params={"code": "CODE#_", "state": q["state"][0]}, follow_redirects=False)
    assert r.status_code in (302, 307) and "connected=instagram" in r.headers["location"]
    form = parse_qs(calls[0].content.decode())
    assert form["code"] == ["CODE"] and form["grant_type"] == ["authorization_code"]
    assert parse_qs(urlparse(str(calls[1].url)).query)["grant_type"] == ["ig_exchange_token"]
    cred = tokens.load(db, "instagram")
    assert cred.access_token == "LONG" and cred.user_id == "1784" and cred.username == "pavlodar_test"
    bad = client.get("/api/connect/instagram/callback", params={"code": "x", "state": "forged"}, follow_redirects=False)
    assert "connect_error" in bad.headers["location"]
    tokens.delete(db, "instagram")


def test_connect_start_requires_admin_and_app(client, operator, admin):
    assert client.get("/api/connect/threads/start", headers=operator).status_code == 403
    r = client.get("/api/connect/threads/start", headers=admin)
    assert r.status_code == 400 and "THREADS_APP_ID" in r.json()["detail"]


# ---------------------------------------------------------------- Telegram improvements
TG_PAGE = """<div class="tgme_widget_message" data-post="pvl/{a}"><div class="tgme_widget_message_text">Пост {a}</div>
<a class="tgme_widget_message_date"><time datetime="2026-10-29T08:00:00+00:00"></time></a></div>
<div class="tgme_widget_message" data-post="pvl/{b}"><div class="tgme_widget_message_text">Пост {b}</div>
<a class="tgme_widget_message_date"><time datetime="2026-10-29T09:00:00+00:00"></time></a></div>"""


def test_telegram_web_incremental(monkeypatch):
    pages = {None: TG_PAGE.format(a=11, b=12)}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url):
            return SimpleNamespace(text=pages.get(None), raise_for_status=lambda: None)

    import app.collectors.telegram_web as tw
    monkeypatch.setattr(tw.httpx, "Client", FakeClient)
    monkeypatch.setattr(tw.time, "sleep", lambda s: None)
    c = TelegramWebCollector({"channels": ["pvl"], "pages": 1})
    c.state = {}
    assert [i.external_id for i in c.fetch(None)] == ["pvl/11", "pvl/12"]
    c2 = TelegramWebCollector({"channels": ["pvl"], "pages": 1})
    c2.state = c.state
    pages[None] = TG_PAGE.format(a=12, b=13)
    assert [i.external_id for i in c2.fetch(None)] == ["pvl/13"]          # only the new post


def test_telegram_web_first_run_reads_older_pages(monkeypatch):
    pages = {"https://t.me/s/pvl": TG_PAGE.format(a=21, b=22), "https://t.me/s/pvl?before=21": TG_PAGE.format(a=11, b=12)}

    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url):
            return SimpleNamespace(text=pages.get(url, ""), raise_for_status=lambda: None)

    import app.collectors.telegram_web as tw
    monkeypatch.setattr(tw.httpx, "Client", FakeClient)
    monkeypatch.setattr(tw.time, "sleep", lambda s: None)
    c = TelegramWebCollector({"channels": ["pvl"], "pages": 2})
    c.state = {}
    assert sorted(i.external_id for i in c.fetch(None)) == ["pvl/11", "pvl/12", "pvl/21", "pvl/22"]


def test_telethon_comment_threading():
    top = SimpleNamespace(id=50, message="Ответ на вопрос", date=NOW, sender_id=1, reactions=None, replies=None,
                          reply_to=SimpleNamespace(reply_to_msg_id=40, reply_to_top_id=30))
    plain = SimpleNamespace(id=40, message="Вопрос", date=NOW, sender_id=2, reactions=None, replies=None,
                            reply_to=SimpleNamespace(reply_to_msg_id=30, reply_to_top_id=None))
    nested, first = comment_item("tipavlo", 7, "Пост о Павлодаре", top), comment_item("tipavlo", 7, "Пост о Павлодаре", plain)
    assert first.kind == "comment" and first.parent_external_id == "tipavlo/7"
    assert nested.kind == "reply" and nested.parent_external_id == "tipavlo/7/c40"
    assert nested.url == "https://t.me/tipavlo/7?comment=50" and nested.context_text == "Пост о Павлодаре"


# ---------------------------------------------------------------- pipeline: geo + cross-platform
def _source(db, platform, type_, scope="city"):
    s = Source(type=type_, name=f"test {platform}", platform=platform, geo_scope=scope, config={}, enabled=False)
    db.add(s)
    db.commit()
    return s


def test_other_city_never_reaches_llm_and_is_excluded(db, client, operator, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "enrich", lambda *a, **k: calls.append(a) or pytest.fail("LLM must not be called"))
    src = _source(db, "telegram", "telegram_web", scope="region")
    run = pipeline.ingest(db, src, [RawItem(external_id="ek1", text="В Экибастузе снова нет отопления в 3 мкр",
                                            published_at=NOW, platform="telegram")])
    assert run.not_local == 1
    pipeline.process_pending(db)
    it = db.scalar(select(Item).where(Item.external_id == "ek1"))
    assert it.geo_status == "not_local" and it.enrichment is None and not calls
    feed = client.get("/api/items", params={"q": "снова нет отопления в 3"}, headers=operator).json()
    assert feed["total"] == 0
    excl = client.get("/api/items", params={"q": "снова нет отопления в 3", "geo": "not_local"}, headers=operator).json()
    assert excl["total"] == 1 and excl["items"][0]["geo_reason"].startswith("Сообщение о другом")


def test_possible_queue_and_operator_decision(db, client, operator):
    src = _source(db, "telegram", "telegram_web", scope="region")
    pipeline.ingest(db, src, [RawItem(external_id="pq1", text="Когда отремонтируют лифт в доме на Камзина?",
                                      published_at=NOW, platform="telegram")])
    pipeline.process_pending(db)
    it = db.scalar(select(Item).where(Item.external_id == "pq1"))
    assert it.geo_status == "possible"
    assert client.get("/api/stats/operations", headers=operator).json()["geo_queue"] >= 1
    q = client.get("/api/items", params={"geo": "possible", "q": "Камзина"}, headers=operator).json()
    assert q["total"] == 1
    r = client.post(f"/api/items/{it.id}/geo", json={"status": "local", "comment": "Камзина — улица Павлодара"},
                    headers=operator)
    assert r.status_code == 200 and r.json()["geo_status"] == "local" and r.json()["geo_reviewed"]
    assert client.get("/api/items", params={"q": "Камзина"}, headers=operator).json()["total"] == 1
    db.expire_all()
    pipeline.apply_geo(db.get(Item, it.id))   # reviewed decisions are never overwritten by reprocessing
    assert db.get(Item, it.id).geo_reviewed


def test_cross_platform_problem_is_one_cluster(db, client, operator):
    texts = {
        "telegram": "Огромная яма на Кутузова у остановки, уже второй месяц не ремонтируют",
        "instagram": "Акимат, когда залатаете яму на Кутузова? Каждый день объезжаем",
        "threads": "Павлодар, Кутузова: яма на дороге стала ещё больше",
    }
    ids = []
    for platform, text in texts.items():
        src = _source(db, platform, {"telegram": "telegram_web", "instagram": "instagram", "threads": "threads"}[platform])
        pipeline.ingest(db, src, [RawItem(external_id=f"x-{platform}", text=text, published_at=NOW,
                                          url=f"https://example.org/{platform}", platform=platform)])
        ids.append(db.scalar(select(Item.id).where(Item.external_id == f"x-{platform}")))
    pipeline.process_pending(db)
    pipeline.after_processing(db)
    clusters = {db.scalar(select(ClusterItem.cluster_id).join(Cluster).where(ClusterItem.item_id == i, Cluster.active.is_(True)))
                for i in ids}
    assert len(clusters) == 1 and None not in clusters
    c = db.get(Cluster, clusters.pop())
    assert {"telegram", "instagram", "threads"} <= set(c.platforms) and c.source_count >= 3
    detail = client.get(f"/api/clusters/{c.id}", headers=operator).json()
    assert detail["multi_platform"]
    urls = {i["url"] for i in detail["items"]}
    assert {"https://example.org/telegram", "https://example.org/instagram", "https://example.org/threads"} <= urls
    ov = client.get("/api/stats/overview", params={"days": 30}, headers=operator).json()
    assert {p["platform"] for p in ov["by_platform"]} >= {"telegram", "instagram", "threads"}
    assert any(p["id"] == c.id for p in ov["multi_platform_problems"])
    only_ig = client.get("/api/items", params={"platform": "instagram", "days": 30}, headers=operator).json()
    assert only_ig["items"] and all(i["platform"] == "instagram" for i in only_ig["items"])


def test_repost_on_another_platform_counts_for_problem(db):
    first = db.scalar(select(Item).where(Item.external_id == "x-telegram"))
    src = _source(db, "threads", "threads")
    run = pipeline.ingest(db, src, [RawItem(external_id="dup-th", text=first.text, published_at=NOW, platform="threads",
                                            url="https://example.org/dup")])
    assert run.duplicates == 1
    pipeline.after_processing(db)
    cid = db.scalar(select(ClusterItem.cluster_id).join(Cluster).where(ClusterItem.item_id == first.id, Cluster.active.is_(True)))
    assert "threads" in db.get(Cluster, cid).platforms


# ---------------------------------------------------------------- sources management
def test_recommended_sources(client, admin, operator):
    rec = client.get("/api/sources/recommended", headers=operator).json()
    keys = {r["key"] for r in rec}
    assert {"tg-tipavlo", "tg-pavlodaronline", "ig-pavlodar-akimdigi"} <= keys
    for r in rec:
        assert r["url"].startswith("https://") and r["verified"] and r["geo_scope"] in ("city", "region", "national")
    assert client.post("/api/sources/recommended/tg-pavlodaronline", headers=operator).status_code == 403
    r = client.post("/api/sources/recommended/tg-pavlodaronline", headers=admin)
    assert r.status_code == 200 and r.json()["platform"] == "telegram" and r.json()["geo_scope"] == "region"
    assert client.post("/api/sources/recommended/tg-pavlodaronline", headers=admin).status_code == 409
    listed = {s["recommended_key"]: s for s in client.get("/api/sources", headers=operator).json()}
    assert listed["tg-pavlodaronline"]["url"] == "https://t.me/pavlodaronline"


def test_source_crud_with_geo_scope(client, admin):
    r = client.post("/api/sources", json={"type": "threads", "name": "Threads: ЖКХ Павлодар", "config": {"keywords": ["ЖКХ Павлодар"]},
                                          "geo_scope": "national", "url": "https://www.threads.com", "description": "поиск"},
                    headers=admin)
    assert r.status_code == 200 and r.json()["platform"] == "threads" and r.json()["connection"] == "never"
    sid = r.json()["id"]
    p = client.patch(f"/api/sources/{sid}", json={"geo_scope": "city", "enabled": False}, headers=admin).json()
    assert p["geo_scope"] == "city" and p["connection"] == "disabled"
    assert client.delete(f"/api/sources/{sid}", headers=admin).status_code == 200


def test_unconnected_platform_run_is_logged(db):
    src = _source(db, "instagram", "instagram")
    src.config = {"own_media": True}
    db.commit()
    run = pipeline.run_source(db, src, "manual")
    assert run.status == "error" and "не подключён" in run.error and src.last_status == "error"


def test_repeat_run_on_sqlite_passes_aware_since(db, monkeypatch):
    """A second run uses last_run_at from the DB; SQLite gives it back without a timezone."""
    import app.collectors.news as news
    seen = {}

    def fake_fetch(self, since):
        seen["since"] = since
        return []

    monkeypatch.setattr(news.NewsCollector, "fetch", fake_fetch)
    src = _source(db, "news", "news")
    src.config = {"feeds": ["https://example.org/rss"]}
    src.last_run_at, src.last_status = datetime(2026, 11, 1, 6, 0), "ok"   # naive, as SQLite returns it
    db.commit()
    assert pipeline.run_source(db, src, "manual").status == "ok"
    assert seen["since"].tzinfo is not None


# ---------------------------------------------------------------- pavon.kz reader comments
PAVON_PAGE = """<html><head><meta property="og:title" content="Зачем красят дымовые трубы ТЭЦ">
<meta itemprop="datePublished" content="2026-12-30T12:00:00+05:00"></head><body>
<script type="application/json" id="comment-wrapper-data">{"comments": [
 {"id": 11, "body": "<blockquote><p>цитата чужих слов</p></blockquote><p>Во дворе опять нет света</p>",
  "time": "31 декабря 23:10 Четверг", "creator": "77", "replyto": null, "like_count": 2},
 {"id": 12, "body": "<p>И у нас тоже</p>", "time": "2 января  1:05 Суббота", "creator": "78", "replyto": 11},
 {"id": 13, "body": "<blockquote>только цитата</blockquote>", "time": "3 января 10:00", "creator": "79"}],
 "pagination": {"total_pages": 1}}</script></body></html>"""


def test_pavon_comments_dates_quotes_and_threads():
    from app.collectors.pavon import parse_article
    from app.serializers import voice

    items, pages = parse_article(PAVON_PAGE, "https://pavon.kz/post/view/1")
    assert pages == 1 and [i.external_id for i in items] == ["pavon:11", "pavon:12"]   # quote-only comment dropped
    first, reply = items
    assert first.text == "Во дворе опять нет света"                     # quoted text is not credited to the reader
    assert first.published_at == datetime(2026, 12, 31, 18, 10, tzinfo=timezone.utc)
    assert reply.published_at == datetime(2027, 1, 1, 20, 5, tzinfo=timezone.utc)  # year rolls over
    assert reply.kind == "reply" and first.kind == "comment" and first.reactions == 2
    assert first.url == first.parent_url == "https://pavon.kz/post/view/1" and "ТЭЦ" in first.context_text
    assert voice(SimpleNamespace(is_direct=False, kind=first.kind, source=SimpleNamespace(type="pavon_comments"))) == "resident"
