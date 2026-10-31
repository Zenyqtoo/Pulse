"""Rule-based analyser.

Two jobs:
1. Cheap spam pre-filter that runs before any LLM call.
2. Transparent fallback when the Claude API key is missing or the API fails. Results are
   stored with model="rules-v1" so the UI and the evaluation never confuse them with LLM output.
"""
import re

from app.ai.schema import Entities, EnrichmentResult

SPAM_WORDS = ["скидк", "акция", "распродаж", "заработ", "подпишись", "подписывайтесь", "реклам", "крипт",
              "казино", "ставки", "букмекер", "доставка", "звоните", "пишите в лс", "в директ", "промокод",
              "кредит без", "займ", "ұтыс", "жеңілдік", "жарнама", "заработок", "инвест"]
_URL = re.compile(r"https?://|www\.|t\.me/|@\w{4,}")
_PRICE = re.compile(r"\d[\d\s]*\s?(тг|тенге|₸|руб|\$)", re.I)

NEG = ["нет ", "не работает", "сломан", "ужас", "кошмар", "безобраз", "плохо", "грязн", "опасн", "жалоб",
       "надоело", "сколько можно", "невозможно", "холодно", "воняет", "яма", "разбит", "отключ", "авари",
       "проблем", "не убира", "не вывоз", "не приезжа", "не отвеча", "очеред", "бардак", "позор", "жоқ",
       "нашар", "қиын", "мәселе", "шағым", "лас", "суық", "бұзыл", "не дождаться", "игнор", "почему",
       "до сих пор", "уже неделю", "уже месяц", "третий день", "второй день", "мерзн", "задерж"]
POS = ["спасибо", "благодар", "отлично", "хорошо", "молодц", "понравил", "здорово", "красиво", "удобно",
       "рахмет", "керемет", "жақсы", "алғыс", "наконец-то сделали", "быстро отреагир", "супер", "чисто"]
SARCASM = ["спасибо за ям", "спасибо акимату за", "браво", "👏", "так держать"]

URGENCY_RULES = {
    "accident": ["авари", "прорыв", "обрушен", "пожар", "затопил", "апат"],
    "life_threat": ["угроза жизни", "угрозу жизни", "опасно для жизни", "оголенн", "оголён", "провода висят",
                    "открытый люк", "открытые люки", "өмірге қауіп", "сымдар ашық", "напали", "покусал", "укусил"],
    "no_water": ["нет воды", "без воды", "отключили воду", "су жоқ", "воды нет"],
    "no_heat": ["нет отоплен", "без отоплен", "холодные батаре", "батареи холодн", "мерзнем", "мёрзнем",
                "жылу жоқ", "отопление не"],
    "no_power": ["нет света", "без света", "отключили свет", "нет электричеств", "жарық жоқ"],
    "children": ["дети", "детей", "ребен", "ребён", "школьник", "балалар", "бала"],
    "elderly": ["пожил", "пенсионер", "бабушк", "дедушк", "қарттар", "зейнеткер"],
}

_DISTRICT = re.compile(r"(?i)\b(\d{1,3}\s*(?:-?й)?\s*мкр|мкр\.?\s*\d{1,3}|микрорайон\w*\s*№?\s*\d{1,3}|"
                       r"\d{1,3}\s*микрорайон\w*|[А-ЯЁ][а-яё]+(?:ский|ой|ий)\s+район\w*|район\w*\s+[А-ЯЁ][а-яё]+|"
                       r"\d{1,3}\s*шағын\s*аудан\w*|поселок\s+[А-ЯЁ][а-яё]+|посёлок\s+[А-ЯЁ][а-яё]+)")
_ADDRESS = re.compile(r"(?i)\b((?:ул\.?|улица|пр\.?|проспект|пр-т|көшесі|бульвар)\s+[А-ЯЁӘҒҚҢӨҰҮҺІ][\w\-]+"
                      r"(?:\s+[А-ЯЁӘҒҚҢӨҰҮҺІ][\w\-]+)?(?:,?\s*(?:д\.|дом)?\s*\d+[а-я]?)?)")
_OBJECT = re.compile(r"(?i)\b((?:школ[аеуы]|гимнази[яи]|детск(?:ий|ом|ого) сад\w*|сад\w*|поликлиник[аиеу]|"
                     r"больниц[аеуы]|остановк[аеи]|дом[ае]?|мектеп)\s*№?\s*\d{1,4})")


PROBLEMS = [  # canonical problem names for the fallback; the LLM produces its own
    ("Оголённые провода", ["оголенн", "оголён", "провода висят", "сымдар"]),
    ("Нет отопления", ["отоплен", "батаре", "жылу", "тепл", "радиатор"]),
    ("Нет воды", ["нет воды", "без воды", "холодной воды", "горячей воды", "су жоқ", "прорыв", "труб"]),
    ("Не работает лифт", ["лифт"]),
    ("Не вывозят мусор", ["мусор", "қоқыс", "контейнер", "мусорные баки", " баки "]),
    ("Ямы на дороге", ["яма", "ямы", "яму", "ямой", "ямам", "ямах", "ямки", "шұңқыр", "асфальт", "дорог"]),
    ("Общественный транспорт", ["автобус", "маршрут", "аялдама", "рейс"]),
    ("Не работает освещение", ["фонар", "освещен", "жарық", "темнот"]),
    ("Уборка снега", ["снег", "гололед", "қар "]),
    ("Очереди в поликлинике", ["поликлиник", "емхана", "терапевт", "педиатр", "талон", "регистратур"]),
    ("Бродячие собаки", ["собак", "иттер", " ит "]),
    ("Выбросы и смог", ["смог", "дым", "выброс", "түтін", "тэц", "ауа ласт", "гари", "сажа"]),
    ("Нехватка мест в детсадах", ["детский сад", "детского сада", "детсад", "садик", "балабақша"]),
    ("Задержка пособий", ["пособи", "выплат", "жәрдемақы"]),
    ("Запись в школу", ["первый класс", "запись в школ"]),
    ("Дом культуры и мероприятия", ["дом культуры", "концерт", "фестивал", "библиотек"]),
    ("Торговля и аренда", ["рынок", "рынк", "аренд", "киоск", "веранд", "разрешени"]),
]

_DISTRICT_NUM = re.compile(r"(?i)(\d{1,3})\s*(?:-?(?:й|ом|м))?\s*(?:мкр|микрорайон|шағын\s*аудан)|"
                           r"(?:мкр\.?|микрорайон\w*)\s*№?\s*(\d{1,3})")
_ORDINALS = {"перв": 1, "втор": 2, "трет": 3, "четверт": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8, "девят": 9,
             "десят": 10}


def normalize_district(value: str | None, text: str = "") -> str | None:
    """'5 микрорайоне', 'мкр 5', '5 шағын ауданда', 'пятом микрорайоне' → '5 мкр'."""
    for src in (value or "", text or ""):
        m = _DISTRICT_NUM.search(src)
        if m:
            return f"{m.group(1) or m.group(2)} мкр"
        low = src.lower()
        for stem, n in _ORDINALS.items():
            if re.search(rf"\b{stem}\w*\s+(микрорайон|мкр)", low):
                return f"{n} мкр"
    return value.strip()[:200] if value and value.strip() else None


def problem_type(text: str) -> str | None:
    t = _norm_norm(text)
    for name, words in PROBLEMS:
        if any(w in t for w in words):
            return name
    return None


def spam_check(text: str) -> tuple[bool, str | None]:
    t = (text or "").lower()
    words = max(1, len(t.split()))
    links = len(_URL.findall(t))
    promo = [w for w in SPAM_WORDS if w in t]
    if len(t.strip()) < 3:
        return True, "пустое сообщение"
    if links / words > 0.15 and links >= 2:
        return True, "много ссылок"
    if len(promo) >= 2:
        return True, "рекламные слова: " + ", ".join(promo[:3])
    if promo and _PRICE.search(t) and links:
        return True, "реклама с ценой и ссылкой"
    return False, None


def _norm_norm(text: str) -> str:
    return " " + (text or "").lower().replace("ё", "е") + " "


def classify_department(text: str, departments: list[dict]) -> tuple[list[str], float, list[str]]:
    t = _norm_norm(text)
    scores: dict[str, float] = {}
    hits_by: dict[str, list[str]] = {}
    for d in departments:
        hits = [k for k in d.get("keywords", []) if k and k.lower().replace("ё", "е") in t]
        if hits:
            scores[d["code"]] = len(hits) + 0.1 * sum(len(h) for h in hits) / 10
            hits_by[d["code"]] = hits
    if not scores:
        return ["other"], 0.35, []
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top_code, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = (top - second) / top
    conf = min(0.85, 0.45 + 0.1 * min(top, 3) + 0.15 * margin)
    depts = [c for c, s in ranked[:3] if s >= top * 0.6]
    return depts, round(conf, 2), hits_by.get(top_code, [])


def sentiment(text: str) -> tuple[str, float, float]:
    t = _norm_norm(text)
    if any(s in t for s in SARCASM) and any(n in t for n in NEG):
        return "negative", -0.6, 0.55
    neg = sum(t.count(w) for w in NEG)
    pos = sum(t.count(w) for w in POS)
    exclam = t.count("!")
    if neg == 0 and pos == 0:
        # a concrete city problem described without praise reads as a complaint
        if problem_type(text) and "?" not in t:
            return "negative", -0.4, 0.45
        return "neutral", 0.0, 0.5
    score = (pos - neg - 0.2 * exclam * (1 if neg > pos else 0)) / max(1, pos + neg)
    score = max(-1.0, min(1.0, score))
    if score <= -0.2:
        return "negative", round(score, 2), 0.6
    if score >= 0.3:
        return "positive", round(score, 2), 0.6
    return "neutral", round(score, 2), 0.45


def message_type(text: str, sent: str) -> str:
    t = _norm_norm(text)
    if any(w in t for w in ["спасибо", "благодар", "рахмет", "алғыс"]) and sent == "positive":
        return "gratitude"
    if any(w in t for w in ["предлага", "предложени", "хорошо бы", "было бы", "давайте", "ұсыныс", "прошу рассмотреть"]):
        return "proposal"
    if "?" in t or any(w in t for w in [" когда ", " почему ", " как ", " куда ", " қашан", " неге", " ма?"]):
        return "question" if sent != "negative" else "complaint"
    if sent == "negative":
        return "complaint"
    return "info"


def urgency(text: str) -> list[str]:
    t = _norm_norm(text)
    return [k for k, words in URGENCY_RULES.items() if any(w in t for w in words)]


def entities(text: str, hits: list[str]) -> Entities:
    d = _DISTRICT.search(text or "")
    a = _ADDRESS.search(text or "")
    o = _OBJECT.search(text or "")
    return Entities(
        district=normalize_district(d.group(1).strip() if d else None, text),
        address=a.group(1).strip() if a else None,
        object=o.group(1).strip() if o else None,
        problem_type=problem_type(text) or (hits[0].strip().capitalize() if hits else None),
    )


PROBLEM_DEPT = {
    "Оголённые провода": "safety", "Нет отопления": "housing", "Нет воды": "housing", "Не работает лифт": "housing",
    "Не вывозят мусор": "housing", "Ямы на дороге": "roads", "Общественный транспорт": "roads",
    "Не работает освещение": "improvement", "Уборка снега": "improvement", "Очереди в поликлинике": "health",
    "Бродячие собаки": "safety", "Выбросы и смог": "ecology", "Нехватка мест в детсадах": "education",
    "Задержка пособий": "social", "Запись в школу": "education", "Дом культуры и мероприятия": "culture",
    "Торговля и аренда": "business",
}


def analyse(text: str, departments: list[dict]) -> EnrichmentResult:
    depts, conf, hits = classify_department(text, departments)
    known = {d["code"] for d in departments}
    prob = problem_type(text)
    pd = PROBLEM_DEPT.get(prob)
    if pd and pd in known and pd != depts[0]:   # a recognised problem decides the department
        depts = [pd] + [d for d in depts if d != pd][:2]
        conf = max(conf, 0.65)
        hits = [prob.lower()] + hits
    sent, score, sconf = sentiment(text)
    mtype = message_type(text, sent)
    spam, reason = spam_check(text)
    markers = urgency(text)
    names = {d["code"]: d["name"] for d in departments}
    rationale = (
        f"Правила: ключевые слова «{', '.join(hits[:3])}» → {names.get(depts[0], depts[0])}"
        if hits else "Правила: ключевые слова подразделений не найдены → Прочее"
    )
    rationale += f"; тональность по словарю: {sent}."
    return EnrichmentResult(
        departments=depts, primary_department=depts[0], department_confidence=conf,
        sentiment=sent, sentiment_score=score, sentiment_confidence=sconf, message_type=mtype,
        is_spam=spam, spam_reason=reason, entities=entities(text, hits),
        urgency_markers=markers, pii_names=[], rationale=rationale,
    )
