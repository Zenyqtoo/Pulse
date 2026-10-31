"""Claude API client: enrichment, cluster summaries, chat and digests.

Every call has a deterministic fallback, so the system keeps working without a key or network.
Fallback results are labelled (model name "rules-v1" / "extractive") and never presented as LLM output.
"""
import json
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from app.ai import prompts, rules
from app.ai.schema import EnrichmentResult, tool_schema
from app.config import get_settings

log = logging.getLogger("pulse.llm")

_client = None


def get_client():
    """Lazily create the Anthropic client. Returns None when no API key is configured."""
    global _client
    s = get_settings()
    if not s.anthropic_api_key:
        return None
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_s, max_retries=3)
    return _client


def set_client(client) -> None:
    """Tests inject a fake client here."""
    global _client
    _client = client


@dataclass
class EnrichOutcome:
    result: EnrichmentResult
    model: str
    latency_ms: int
    error: str | None = None


def _departments_block(departments: list[dict]) -> str:
    return "\n".join(f"- {d['code']} — {d['name']} — {d.get('description', '')}" for d in departments)


def _examples_block(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = ["\nИСПРАВЛЕНИЯ ОПЕРАТОРОВ (учитывай их как образцы):"]
    for ex in examples[:12]:
        lines.append(f"Сообщение: «{ex['text'][:300]}» → {ex['label']}")
    return "\n".join(lines)


def build_system(departments: list[dict], examples: list[dict]) -> list[dict]:
    text = prompts.ENRICH_SYSTEM.format(departments=_departments_block(departments),
                                        extra_examples=_examples_block(examples), city=get_settings().city_name)
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _tool_input(resp, name: str) -> dict:
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == name:
            return block.input
    raise ValueError("Модель не вернула вызов инструмента")


def _user_message(text_masked: str, context: dict | None) -> str:
    parts = []
    if context:
        if context.get("source"):
            parts.append(f"Источник: {context['source']}")
        if context.get("platform"):
            parts.append(f"Платформа: {context['platform']}; тип: {context.get('kind', 'post')}")
        if context.get("parent_text"):
            parts.append(f"Пост, к которому написан комментарий: «{context['parent_text'][:600]}»")
    parts.append(f"Сообщение:\n«{text_masked[:4000]}»")
    return "\n".join(parts)


def enrich(text_masked: str, departments: list[dict], examples: list[dict] | None = None,
           context: dict | None = None) -> EnrichOutcome:
    """One structured call per message. Falls back to rules on missing key, API error or invalid JSON."""
    s = get_settings()
    allowed = {d["code"] for d in departments}
    started = time.perf_counter()
    client = get_client()
    if client is None:
        res = rules.analyse(text_masked, departments).validate_departments(allowed)
        return EnrichOutcome(res, "rules-v1", int((time.perf_counter() - started) * 1000))

    tool = {"name": "record_analysis", "description": "Сохранить разбор обращения",
            "input_schema": tool_schema(sorted(allowed))}
    messages = [{"role": "user", "content": _user_message(text_masked, context)}]
    last_err = None
    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=s.llm_model_enrich, max_tokens=700, temperature=0,
                system=build_system(departments, examples or []),
                tools=[tool], tool_choice={"type": "tool", "name": "record_analysis"},
                messages=messages,
            )
            data = _tool_input(resp, "record_analysis")
            res = EnrichmentResult.model_validate(data).validate_departments(allowed)
            return EnrichOutcome(res, s.llm_model_enrich, int((time.perf_counter() - started) * 1000))
        except ValidationError as e:  # model returned something off-schema: ask once more with the error
            last_err = f"invalid JSON: {e.errors()[:2]}"
            messages = messages[:1] + [
                {"role": "assistant", "content": "Ответ не прошёл проверку схемы."},
                {"role": "user", "content": f"Исправь и вызови record_analysis снова. Ошибка: {str(e)[:400]}"},
            ]
        except Exception as e:  # network / API errors after SDK retries
            last_err = f"{type(e).__name__}: {str(e)[:300]}"
            break
    log.warning("LLM enrichment failed, using rules fallback: %s", last_err)
    res = rules.analyse(text_masked, departments).validate_departments(allowed)
    return EnrichOutcome(res, "rules-v1 (fallback)", int((time.perf_counter() - started) * 1000), error=last_err)


def summarise_cluster(texts: list[str], hint_title: str) -> tuple[str, str, str]:
    """Return (title, summary, model). Extractive fallback without the API."""
    client = get_client()
    sample = texts[:20]
    if client is not None:
        try:
            tool = {"name": "record_cluster", "description": "Название и резюме проблемы",
                    "input_schema": {"type": "object", "properties": {
                        "title": {"type": "string"}, "summary": {"type": "string"}},
                        "required": ["title", "summary"]}}
            body = "\n".join(f"{i + 1}. {t[:400]}" for i, t in enumerate(sample))
            resp = client.messages.create(
                model=get_settings().llm_model_summary, max_tokens=400, temperature=0,
                system=prompts.SUMMARY_SYSTEM, tools=[tool],
                tool_choice={"type": "tool", "name": "record_cluster"},
                messages=[{"role": "user", "content": f"Всего обращений: {len(texts)}\n{body}"}],
            )
            data = _tool_input(resp, "record_cluster")
            return data["title"][:280], data["summary"], get_settings().llm_model_summary
        except Exception as e:
            log.warning("cluster summary failed: %s", e)
    first = sample[0][:220] + ("…" if len(sample[0]) > 220 else "") if sample else ""
    summary = f"{len(texts)} обращ. по теме «{hint_title}». Пример: {first}"
    return hint_title, summary, "extractive"


def complete_text(system: str, user: str, max_tokens: int = 900) -> tuple[str | None, str | None]:
    """Free-text completion for chat and digests. Returns (text, model) or (None, None) without API."""
    client = get_client()
    if client is None:
        return None, None
    try:
        resp = client.messages.create(model=get_settings().llm_model_summary, max_tokens=max_tokens,
                                      temperature=0.2, system=system,
                                      messages=[{"role": "user", "content": user}])
        text = "".join(getattr(b, "text", "") for b in resp.content)
        return text, get_settings().llm_model_summary
    except Exception as e:
        log.warning("completion failed: %s", e)
        return None, None


def parse_filters(question: str, dept_codes: list[str]) -> dict:
    """Ask the model to turn a chat question into feed filters. Rules fallback otherwise."""
    client = get_client()
    if client is not None:
        try:
            tool = {"name": "set_filters", "description": "Фильтры для поиска обращений",
                    "input_schema": {"type": "object", "properties": {
                        "department": {"type": ["string", "null"], "enum": dept_codes + [None]},
                        "sentiment": {"type": ["string", "null"], "enum": ["positive", "neutral", "negative", None]},
                        "days": {"type": ["integer", "null"], "description": "Период в днях"},
                        "district": {"type": ["string", "null"]},
                        "query": {"type": ["string", "null"], "description": "Ключевые слова для полнотекстового поиска"},
                    }}}
            resp = get_client().messages.create(
                model=get_settings().llm_model_enrich, max_tokens=200, temperature=0,
                system="Преобразуй вопрос аналитика в фильтры. Коды подразделений: " + ", ".join(dept_codes),
                tools=[tool], tool_choice={"type": "tool", "name": "set_filters"},
                messages=[{"role": "user", "content": question}])
            return {k: v for k, v in _tool_input(resp, "set_filters").items() if v}
        except Exception as e:
            log.warning("filter parsing failed: %s", e)
    return rules_filters(question)


def rules_filters(question: str) -> dict:
    from app.reference import DEPARTMENTS

    q = question.lower()
    f: dict = {}
    for d in DEPARTMENTS:
        if d["name"].lower() in q or any(k in q for k in d["keywords"][:6]):
            f["department"] = d["code"]
            break
    if any(w in q for w in ["негатив", "жалоб", "плох", "отрицат"]):
        f["sentiment"] = "negative"
    elif any(w in q for w in ["позитив", "благодар", "положит"]):
        f["sentiment"] = "positive"
    if "сегодня" in q or "сутки" in q:
        f["days"] = 1
    elif "недел" in q:
        f["days"] = 7
    elif "месяц" in q:
        f["days"] = 30
    return f


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
