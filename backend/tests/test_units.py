"""Unit tests: masking, language, spam, parsers, priority, LLM structured output + fallbacks."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.ai import llm, priority, rules
from app.ai.lang import detect_language
from app.ai.masking import mask_extra_names, mask_pii
from app.collectors.news import parse_feed
from app.collectors.telegram_bot import updates_to_items
from app.collectors.telegram_web import parse_page
from app.collectors.upload import parse_upload
from app.reference import DEPARTMENTS

# ---------------------------------------------------------------- masking
def test_mask_structured_identifiers():
    text = "ИИН 850312300123, тел +7 701 234 56 78 и 8 (777) 123-45-67, почта a.b@mail.kz, карта 4400 4300 1234 5678"
    out, kinds = mask_pii(text)
    for secret in ["850312300123", "701 234", "777", "a.b@mail.kz", "4400"]:
        assert secret not in out
    assert {"iin", "phone", "email", "card"} <= set(kinds)


def test_mask_first_names_without_patronymic():
    out, kinds = mask_pii("Павлодар. Иван Петров: нет света. Номер для связи, Жанар")
    assert "Иван" not in out and "Петров" not in out and "Жанар" not in out and "name" in kinds
    # everyday words that are also names stay intact
    assert mask_pii("Канат порвался, вера в ремонт пропала")[0] == "Канат порвался, вера в ремонт пропала"


def test_mask_names_and_apartments():
    out, kinds = mask_pii("Меня зовут Айгерим Сейткали, Иванов Сергей Петрович, Петров И.И. живёт в кв. 45")
    assert "Айгерим" not in out and "Сергей" not in out and "Петров" not in out and "45" not in out
    assert "name" in kinds and "apartment" in kinds


def test_direct_hides_house_number_keeps_street():
    out, _ = mask_pii("В доме по ул. Абая 12 нет воды", strict_address=True)
    assert "Абая" in out and "12" not in out


def test_public_keeps_problem_location():
    out, _ = mask_pii("Яма на ул. Абая 12 у остановки")
    assert "Абая 12" in out


def test_second_pass_names():
    out, changed = mask_extra_names("Номер для связи, Жанар", ["Жанар"])
    assert changed and "Жанар" not in out


# ---------------------------------------------------------------- language / rules
def test_language():
    assert detect_language("В 5 мкр нет отопления уже три дня") == "ru"
    assert detect_language("Біздің аулада екі аптадан бері жарық жоқ, балалар қараңғыда") == "kk"
    assert detect_language("Hello world this is english") == "other"


def test_spam():
    assert rules.spam_check("Скидки до 70%! Акция, пишите в директ, доставка")[0]
    assert not rules.spam_check("На Торайгырова огромные ямы, пробил колесо")[0]


def test_rules_fallback_classifies():
    r = rules.analyse("Третий день нет отопления в 5 мкр, дети мерзнут", DEPARTMENTS)
    assert r.primary_department == "housing" and r.sentiment == "negative"
    assert "no_heat" in r.urgency_markers and "children" in r.urgency_markers
    assert r.entities.district == "5 мкр"
    assert r.rationale.startswith("Правила")


def test_district_normalisation():
    for s in ["5 микрорайоне", "мкр 5", "5 шағын ауданда", "в пятом микрорайоне"]:
        assert rules.normalize_district(None, s) == "5 мкр", s


# ---------------------------------------------------------------- collectors
TG_HTML = """
<div class="tgme_widget_message" data-post="citynews/101">
  <div class="tgme_widget_message_text">Опять ямы на Торайгырова<br/>Когда починят?</div>
  <span class="tgme_widget_message_views">1.2K</span>
  <a class="tgme_widget_message_date"><time datetime="2026-10-29T08:15:00+00:00"></time></a>
</div>
<div class="tgme_widget_message" data-post="citynews/102">
  <div class="tgme_widget_message_text">Нет воды в 7 мкр</div>
  <a class="tgme_widget_message_date"><time datetime="2026-10-29T09:00:00+00:00"></time></a>
</div>
<div class="tgme_widget_message" data-post="citynews/103"><div class="photo-only"></div>
  <a class="tgme_widget_message_date"><time datetime="2026-10-29T09:30:00+00:00"></time></a></div>
"""


def test_telegram_web_parser():
    items = parse_page(TG_HTML, "citynews")
    assert [i.external_id for i in items] == ["citynews/101", "citynews/102"]
    assert items[0].views == 1200 and "\n" in items[0].text
    assert items[0].url == "https://t.me/citynews/101"
    assert items[0].published_at == datetime(2026, 10, 29, 8, 15, tzinfo=timezone.utc)


def test_rss_parser():
    xml = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
    <item><title>В городе отключат воду</title><link>https://news.example/1</link>
    <description>&lt;p&gt;Плановые работы на сетях&lt;/p&gt;</description>
    <pubDate>Wed, 28 Oct 2026 10:00:00 +0500</pubDate><guid>n1</guid></item></channel></rss>"""
    items = parse_feed(xml)
    assert len(items) == 1 and items[0].external_id == "n1"
    assert "Плановые работы" in items[0].text and items[0].published_at.hour == 5


def test_bot_updates():
    updates = [
        {"update_id": 10, "message": {"message_id": 1, "date": 1761800000, "chat": {"id": 55, "type": "private"},
                                      "from": {"id": 55}, "text": "/start"}},
        {"update_id": 11, "message": {"message_id": 2, "date": 1761800100, "chat": {"id": 55, "type": "private"},
                                      "from": {"id": 55}, "text": "Нет света во дворе"}},
        {"update_id": 12, "message": {"message_id": 3, "date": 1761800200, "chat": {"id": -1, "type": "group"},
                                      "text": "group chatter"}},
    ]
    items, offset, greet = updates_to_items(updates)
    assert offset == 13 and greet == [55]
    assert len(items) == 1 and items[0].is_direct and items[0].extra["reply_ref"]["chat_id"] == 55


def test_upload_csv_semicolon_and_dates():
    data = "Текст;Дата;Ссылка\nЯма на дороге;29.10.2026 14:30;https://x\n;;\nНет воды;2026-10-28;\n".encode()
    items, warnings = parse_upload("export.csv", data)
    assert len(items) == 2 and items[0].url == "https://x"
    assert items[0].published_at.day == 29 and not warnings


# ---------------------------------------------------------------- priority
def test_priority_transparent_and_life_threat():
    level, score, f = priority.compute(priority.PriorityInput(1.0, 10, 6, 2, 300, {"no_heat", "children"}, 3))
    assert level == "high" and abs(score - sum(t["points"] for t in f["terms"].values())) < 0.3
    level2, score2, f2 = priority.compute(priority.PriorityInput(0.0, 1, 0, 0, 0, {"life_threat"}, 0))
    assert level2 == "high" and f2["forced_by_life_threat"]
    level3, _, _ = priority.compute(priority.PriorityInput(0.2, 2, 0, 0, 0, set(), 1))
    assert level3 == "low"


# ---------------------------------------------------------------- LLM structured output
class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        assert kw["tool_choice"]["type"] == "tool"
        p = self.payloads.pop(0)
        if isinstance(p, Exception):
            raise p
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=kw["tool_choice"]["name"], input=p)])


GOOD = {"departments": ["roads"], "primary_department": "roads", "department_confidence": 0.93,
        "sentiment": "negative", "sentiment_score": -0.7, "sentiment_confidence": 0.9, "message_type": "complaint",
        "is_spam": False, "entities": {"district": None, "address": "ул. Торайгырова", "object": None,
                                       "problem_type": "Ямы на дороге"},
        "urgency_markers": ["no_heat", "made_up_marker"], "pii_names": [], "rationale": "Сарказм про ямы."}


def test_llm_valid_output(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "anthropic_api_key", "test")
    llm.set_client(FakeClient([GOOD]))
    out = llm.enrich("Спасибо за ямы 👏", DEPARTMENTS)
    assert out.model == llm.get_settings().llm_model_enrich and out.error is None
    assert out.result.primary_department == "roads" and out.result.urgency_markers == ["no_heat"]


def test_llm_invalid_then_fixed(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "anthropic_api_key", "test")
    bad = dict(GOOD, department_confidence=7)
    fake = FakeClient([bad, GOOD])
    llm.set_client(fake)
    out = llm.enrich("текст", DEPARTMENTS)
    assert fake.calls == 2 and out.result.department_confidence == 0.93


def test_llm_error_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "anthropic_api_key", "test")
    llm.set_client(FakeClient([RuntimeError("overloaded")]))
    out = llm.enrich("Нет отопления в 5 мкр", DEPARTMENTS)
    assert out.model == "rules-v1 (fallback)" and "overloaded" in out.error
    assert out.result.primary_department == "housing"


def test_unknown_department_is_coerced(monkeypatch):
    monkeypatch.setattr(llm.get_settings(), "anthropic_api_key", "test")
    llm.set_client(FakeClient([dict(GOOD, departments=["nope"], primary_department="nope")]))
    out = llm.enrich("x", DEPARTMENTS)
    assert out.result.primary_department == "other"


def test_channel_self_promo_is_spam():
    from app.ai.rules import spam_check
    assert spam_check("🌱 Если вам полезны новости о Павлодаре, подпишитесь на канал «Павлодарец»")[0]
    assert not spam_check("Подписали договор на ремонт канала у дамбы")[0]
