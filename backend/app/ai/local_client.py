"""Optional adapter for the loopback-only experimental model service.

No torch/transformers imported by the production backend. Disabled by default.
"""
import re
from urllib.parse import urlsplit

import httpx

from app.ai import rules
from app.ai.schema import Geo


def local_url(value):
    url = urlsplit(value)
    if (url.scheme != "http" or url.hostname not in ("localhost","127.0.0.1","::1")
        or url.username or url.password or url.path not in ("","/") or url.query or url.fragment):
        raise ValueError("Experimental model must use a loopback HTTP address")
    return value.rstrip("/") + "/predict"


def convert(payload,text,departments):
    predictions = payload["predictions"]
    version = payload["version"]
    if not isinstance(version,str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}",version):
        raise ValueError("Invalid model version")
    labels = {k:predictions[k]["label"] for k in ("department","sentiment","message_type","geo")}
    if labels["department"] not in {d["code"] for d in departments}:
        raise ValueError("Unknown department")
    if labels["sentiment"] not in ("negative","neutral","positive") or labels["message_type"] not in (
        "complaint","question","proposal","gratitude","info") or labels["geo"] not in ("local","possible","not_local"):
        raise ValueError("Invalid classifier labels")
    # Keep deterministic entity/urgency/spam extraction; replace only trained tasks.
    result = rules.analyse(text,departments)
    result.primary_department = labels["department"]
    result.departments = [labels["department"]]
    result.sentiment = labels["sentiment"]
    result.sentiment_score = {"negative":-0.5,"neutral":0.,"positive":0.5}[labels["sentiment"]]
    result.message_type = labels["message_type"]
    # Scores have not been calibrated; never pass the prototype as confident AI.
    result.department_confidence = 0.0
    result.sentiment_confidence = 0.0
    result.geo = Geo(relevance="possible", reason="Экспериментальная модель: географию нужно проверить")
    result.rationale = (f"Экспериментальная локальная модель {version}. Автоматическая/AI-разметка; "
                        f"качество не подтверждено независимо. Требуется проверка сотрудника. "
                        f"Предположение о географии: {labels['geo']}.")
    return result, "local:" + version


def analyse(text,departments,context,settings):
    body = {"text":text[:6000],"context":(context or {}).get("parent_text","")[:2000],
            "kind":(context or {}).get("kind","")}
    with httpx.Client(timeout=max(1.,min(30.,settings.local_model_timeout_s)),
                      follow_redirects=False,trust_env=False) as client:
        response = client.post(local_url(settings.local_model_url),json=body)
        response.raise_for_status()
        return convert(response.json(),text,departments)
