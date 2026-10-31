"""Geographic relevance: does a message concern Pavlodar city?

local      — clearly about Pavlodar city → main analytics, clusters, priorities
possible   — may be about the city, location uncertain → separate operator queue
not_local  — another settlement/region, or Pavlodar only mentioned in passing → excluded

Two stages, both explainable:
1. classify_rules(): gazetteer evidence + the source's geographic scope + the parent post's context.
   If the text is clearly about another place, the LLM is not called at all.
2. combine(): merges the rules result with the LLM's contextual judgement (it sees the message,
   the source description and the parent post), so keyword matches alone never decide.
"""
from dataclasses import dataclass, field

from app.geo import pavlodar as gz


@dataclass
class GeoResult:
    status: str
    score: float
    reason: str
    evidence: dict = field(default_factory=dict)
    certain: bool = False   # rules are confident enough to skip the LLM


SCOPE_PRIOR = {"city": 2.0, "region": 0.5, "unknown": 0.0, "national": -1.0}
SCOPE_LABEL = {"city": "источник о городе Павлодар", "region": "источник о Павлодарской области",
               "national": "общенациональный источник", "unknown": "охват источника не указан"}


def _find(text: str) -> dict:
    t = (text or "").lower().replace("ё", "е")
    city = sorted({m.group(0) for r in gz.CITY_RE for m in r.finditer(t)})
    region = sorted({m.group(0) for r in gz.REGION_RE for m in r.finditer(t)})
    medium = [w for w in gz.MEDIUM if w in t]
    weak = [w for w in gz.WEAK if w in t]
    suburbs = [w for w in gz.SUBURBS if w in t]
    other = [name for name, rs in gz.OTHER_RE.items() if any(r.search(t) for r in rs)]
    return {"city": city, "region": region, "landmarks": medium, "streets": weak, "suburbs": suburbs, "other": other}


def classify_rules(text: str, scope: str = "unknown", context: str | None = None) -> GeoResult:
    ev = _find(text)
    ctx = _find(context) if context else {k: [] for k in ev}
    prior = SCOPE_PRIOR.get(scope, 0.0)
    score = (3 * bool(ev["city"]) + 2 * min(2, len(ev["landmarks"])) + 1 * min(2, len(ev["streets"]))
             + 0.5 * bool(ev["suburbs"]) + 2 * bool(ctx["city"] or ctx["landmarks"]) + prior)
    evidence = {k: v for k, v in ev.items() if v}
    if any(ctx.values()):
        evidence["context"] = {k: v for k, v in ctx.items() if v}
    evidence["scope"] = scope
    others = ev["other"] or ([] if (ev["city"] or ev["landmarks"]) else ctx["other"])
    city_strong = bool(ev["city"] or ev["landmarks"])

    if others and not city_strong:
        if ev["streets"] or ev["suburbs"] or (scope == "city" and not ev["other"]):
            return GeoResult("possible", score - 3, f"Упомянуто: {', '.join(others)}; есть признаки Павлодара — нужна проверка",
                             evidence)
        return GeoResult("not_local", score - 3, f"Сообщение о другом населённом пункте: {', '.join(others)}", evidence, certain=True)
    if city_strong and others:
        return GeoResult("possible", score, f"Упомянуты Павлодар и {', '.join(others)} — нужно уточнить, к чему относится проблема",
                         evidence)
    if ev["city"]:
        return GeoResult("local", score, f"Упоминается город: {ev['city'][0]}", evidence)
    if ev["landmarks"]:
        return GeoResult("local", score, f"Городской объект Павлодара: {ev['landmarks'][0]}", evidence)
    if ev["region"] and not ev["streets"]:
        return GeoResult("possible", score, "Упомянута только Павлодарская область, город не указан", evidence)
    if scope == "city":
        return GeoResult("local", score, "Нет признаков другого места; " + SCOPE_LABEL["city"], evidence)
    if ctx["city"] or ctx["landmarks"]:
        return GeoResult("local", score, "Комментарий к посту о Павлодаре", evidence)
    if ev["streets"] or ev["suburbs"] or scope in ("region", "unknown"):
        why = f"улица/район, встречающиеся и в других городах: {', '.join((ev['streets'] + ev['suburbs'])[:3])}" \
            if (ev["streets"] or ev["suburbs"]) else SCOPE_LABEL.get(scope, "")
        return GeoResult("possible", score, f"Место не указано явно ({why})", evidence)
    return GeoResult("not_local", score, "Нет признаков, что сообщение касается Павлодара; " + SCOPE_LABEL[scope], evidence,
                     certain=False)


def combine(rules: GeoResult, llm_relevance: str | None, llm_reason: str | None, scope: str) -> GeoResult:
    """Final decision. The LLM decides context; rules veto obvious contradictions."""
    if rules.certain or llm_relevance not in ("local", "possible", "not_local"):
        return rules
    ev = rules.evidence
    others = bool(ev.get("other"))
    strong = bool(ev.get("city") or ev.get("landmarks"))
    why = f"ИИ: {llm_reason}" if llm_reason else "ИИ"
    if llm_relevance == "local":
        if others and not strong:
            return GeoResult("possible", rules.score, f"{why}; но в тексте упомянуто другое место", ev)
        return GeoResult("local", rules.score + 1, why, ev)
    if llm_relevance == "possible":
        if rules.status == "local" and strong and not others:
            return GeoResult("local", rules.score, f"{rules.reason}; {why}", ev)
        return GeoResult("possible", rules.score, why, ev)
    # not_local
    if strong and scope == "city" and not others:
        return GeoResult("possible", rules.score, f"{why}; при этом упомянут Павлодар — нужна проверка", ev)
    return GeoResult("not_local", rules.score - 1, why, ev)
