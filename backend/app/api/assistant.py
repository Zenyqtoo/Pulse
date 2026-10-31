"""Natural-language assistant (spec 3.5.5) and per-department digest (3.4.5).

Retrieval: question → filters (LLM or rules) → candidate items → TF-IDF/embedding similarity →
top items + aggregates → answer with [#id] references. Works without the API (template answer).
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import embeddings, llm, prompts
from app.api.items import query_items
from app.audit import audit
from app.db import get_db
from app.filters import Filters
from app.models import Cluster, Department, User
from app.reference import DEPT_NAMES, PRIORITY_NAMES, SENTIMENT_NAMES
from app.security import get_current_user
from app.serializers import cluster_dict

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _filters_from(parsed: dict) -> Filters:
    f = Filters(days=parsed.get("days") or 30)
    if parsed.get("department"):
        f.departments = [parsed["department"]]
    if parsed.get("sentiment"):
        f.sentiments = [parsed["sentiment"]]
    if parsed.get("district"):
        f.q = parsed["district"]
    return f


@router.post("/ask")
def ask(body: Ask, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    codes = list(db.scalars(select(Department.code)).all())
    parsed = llm.parse_filters(body.question, codes)
    f = _filters_from(parsed)
    items, total = query_items(db, f, user, "date_desc", 400)
    if not items and f.sentiments:  # widen once
        f.sentiments = None
        items, total = query_items(db, f, user, "date_desc", 400)
    top = items
    if len(items) > 12:
        vecs = embeddings.embed([body.question] + [i.text_masked for i in items])
        sims = vecs[1:] @ vecs[0]
        order = np.argsort(-sims)[:12]
        top = [items[i] for i in order]
    sent = Counter(i.enrichment.sentiment for i in items if i.enrichment)
    cstmt = select(Cluster).where(Cluster.active.is_(True))
    if f.departments:
        cstmt = cstmt.where(Cluster.department.in_(f.departments))
    if user.department_code:
        cstmt = cstmt.where(Cluster.department == user.department_code)
    clusters = db.scalars(cstmt.order_by(Cluster.priority_score.desc()).limit(5)).all()
    context = [f"Период: последние {f.days} дн.; подразделение: "
               f"{', '.join(DEPT_NAMES.get(d, d) for d in f.departments) if f.departments else 'все'}; "
               f"найдено обращений: {total}; тональность: " +
               ", ".join(f"{SENTIMENT_NAMES[k]} {v}" for k, v in sent.items()),
               "Главные проблемы (кластеры):"]
    context += [f"[P#{c.id}] {c.title} — {c.item_count} обращ., приоритет {PRIORITY_NAMES[c.priority]}, "
                f"за 24 ч: {c.count_24h}. {c.summary[:300]}" for c in clusters]
    context.append("Обращения:")
    context += [f"[#{i.id}] {i.published_at.strftime('%d.%m')} {DEPT_NAMES.get(i.enrichment.primary_department, '')}, "
                f"{SENTIMENT_NAMES.get(i.enrichment.sentiment, '')}: {i.text_masked[:350]}" for i in top]
    answer, model = llm.complete_text(prompts.CHAT_SYSTEM, "\n".join(context) + f"\n\nВопрос: {body.question}")
    if answer is None:
        model = "template (без LLM)"
        lines = [f"По запросу найдено {total} обращений за последние {f.days} дн."
                 + (f" Отрицательных: {sent.get('negative', 0)}." if sent else "")]
        if clusters:
            lines.append("Главные проблемы:")
            lines += [f"• [P#{c.id}] {c.title} — {c.item_count} обращ., приоритет {PRIORITY_NAMES[c.priority].lower()}"
                      for c in clusters]
        if top:
            lines.append("Наиболее близкие обращения: " + ", ".join(f"[#{i.id}]" for i in top[:6]))
        answer = "\n".join(lines)
    audit(db, user, "assistant.ask", question=body.question[:200])
    db.commit()
    return {"answer": answer, "model": model, "filters": parsed, "total": total,
            "items": [{"id": i.id, "text": i.text_masked[:240], "published_at": i.published_at.isoformat(),
                       "department": i.enrichment.primary_department, "sentiment": i.enrichment.sentiment,
                       "url": i.url} for i in top],
            "clusters": [cluster_dict(c) for c in clusters]}


@router.get("/digest")
def digest(department: str | None = None, days: int = 7, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    dept = user.department_code or department
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(Cluster).where(Cluster.active.is_(True), Cluster.last_seen >= since)
    if dept:
        stmt = stmt.where(Cluster.department == dept)
    clusters = db.scalars(stmt.order_by(Cluster.priority_score.desc()).limit(12)).all()
    f = Filters(days=days, departments=[dept] if dept else None)
    _, total = query_items(db, f, user, limit=1)
    ctx = "\n".join(f"[P#{c.id}] {c.title}; {DEPT_NAMES.get(c.department)}; {c.item_count} обращ. "
                    f"(за 24 ч {c.count_24h}, ранее {c.count_prev_24h}); приоритет {PRIORITY_NAMES[c.priority]}; "
                    f"статус {c.status}; {c.summary[:300]}" for c in clusters)
    text, model = (None, None)
    if clusters:
        text, model = llm.complete_text(prompts.DIGEST_SYSTEM,
                                        f"Подразделение: {DEPT_NAMES.get(dept, 'все')}; период {days} дн.; "
                                        f"всего обращений {total}.\n{ctx}", 700)
    if text is None:
        model = "template (без LLM)"
        text = "\n".join([f"За {days} дн.: {total} обращений, активных проблем: {len(clusters)}."] +
                         [f"• [P#{c.id}] {c.title} — {c.item_count} обращ., приоритет {PRIORITY_NAMES[c.priority].lower()}"
                          + (f", +{c.count_24h} за сутки" if c.count_24h else "") for c in clusters[:7]])
    return {"department": dept, "days": days, "total": total, "text": text, "model": model,
            "clusters": [cluster_dict(c) for c in clusters]}
