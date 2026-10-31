from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.ai import llm
from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.filters import Filters, apply_item_filters, filters_dep
from app.models import Cluster, ClusterItem, Correction, Department, Enrichment, GoldLabel, Item, User, utcnow
from app.security import can_see_original, get_current_user, require_role
from app.serializers import item_dict

router = APIRouter(prefix="/api/items", tags=["items"])

SORTS = {
    "date_desc": Item.published_at.desc(), "date_asc": Item.published_at.asc(),
    "confidence_asc": Enrichment.dept_confidence.asc(), "sentiment_asc": Enrichment.sentiment_score.asc(),
    "reach_desc": (Item.reactions + Item.replies).desc(),
}


def set_item_status(item: Item, status: str) -> None:
    now = utcnow()
    item.status = status
    item.status_changed_at = now
    if status == "transferred" and not item.transferred_at:
        item.transferred_at = now
    if status in ("resolved", "closed") and not item.resolved_at:
        item.resolved_at = now
        if not item.transferred_at:
            item.transferred_at = now


def _clusters_for(db: Session, ids: list[int]) -> dict[int, Cluster]:
    if not ids:
        return {}
    rows = db.execute(select(ClusterItem.item_id, Cluster).join(Cluster, Cluster.id == ClusterItem.cluster_id)
                      .where(ClusterItem.item_id.in_(ids), Cluster.active.is_(True))).all()
    return {item_id: c for item_id, c in rows}


def query_items(db: Session, f: Filters, user: User, sort: str = "date_desc", limit: int | None = None,
                offset: int = 0) -> tuple[list[Item], int]:
    join = Item.enrichment
    outer = f.include_spam or f.geo in ("not_local", "all")   # excluded items may have no AI analysis
    stmt = select(Item).outerjoin(Enrichment, Enrichment.item_id == Item.id) if outer else \
        select(Item).join(Enrichment, Enrichment.item_id == Item.id)
    stmt = apply_item_filters(stmt, f, user, analytics=False)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.options(joinedload(join), joinedload(Item.source)).order_by(SORTS.get(sort, SORTS["date_desc"]), Item.id.desc())
    if limit:
        stmt = stmt.limit(limit).offset(offset)
    return db.scalars(stmt).unique().all(), total


@router.get("")
def list_items(f: Filters = Depends(filters_dep), sort: str = "date_desc",
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items, total = query_items(db, f, user, sort, page_size, (page - 1) * page_size)
    clusters = _clusters_for(db, [i.id for i in items])
    return {"total": total, "page": page, "page_size": page_size,
            "items": [item_dict(i, clusters.get(i.id)) for i in items]}


def _get_visible(db: Session, item_id: int, user: User) -> Item:
    it = db.get(Item, item_id, options=[joinedload(Item.enrichment), joinedload(Item.source)])
    if it is None:
        raise HTTPException(404, "Обращение не найдено")
    if it.is_direct and user.role == "viewer":
        raise HTTPException(403, "Личные обращения (Direct) доступны только уполномоченным ролям")
    if user.department_code and (not it.enrichment or it.enrichment.primary_department != user.department_code):
        raise HTTPException(403, "Обращение относится к другому подразделению")
    return it


@router.get("/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    it = _get_visible(db, item_id, user)
    c = _clusters_for(db, [it.id]).get(it.id)
    d = item_dict(it, c, full=True)
    d["corrections"] = [
        {"field": x.field, "old": x.old_value, "new": x.new_value, "comment": x.comment,
         "at": x.created_at.isoformat(), "user_id": x.user_id}
        for x in db.scalars(select(Correction).where(Correction.item_id == it.id).order_by(Correction.created_at)).all()
    ]
    g = db.get(GoldLabel, it.id)
    d["gold"] = {"department": g.department, "sentiment": g.sentiment, "split": g.split} if g else None
    d["can_view_original"] = can_see_original(user)
    if it.is_direct:
        audit(db, user, "direct.view_masked", "item", it.id)
        db.commit()
    return d


@router.get("/{item_id}/original")
def get_original(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    it = _get_visible(db, item_id, user)
    audit(db, user, "item.view_original", "item", it.id, direct=it.is_direct)
    db.commit()
    return {"id": it.id, "text": it.text, "is_direct": it.is_direct}


class Correct(BaseModel):
    department: str | None = None
    sentiment: Literal["positive", "neutral", "negative"] | None = None
    message_type: Literal["complaint", "question", "proposal", "gratitude", "info"] | None = None
    status: Literal["new", "transferred", "in_progress", "resolved", "closed"] | None = None
    comment: str | None = Field(None, max_length=500)


@router.patch("/{item_id}")
def correct_item(item_id: int, body: Correct, db: Session = Depends(get_db),
                 user: User = Depends(require_role("operator"))):
    it = _get_visible(db, item_id, user)
    e = it.enrichment
    changes = []
    if body.department:
        if not db.scalar(select(Department.id).where(Department.code == body.department)):
            raise HTTPException(400, "Неизвестное подразделение")
        if e and e.primary_department != body.department:
            changes.append(("department", e.primary_department, body.department))
            e.primary_department = body.department
            e.departments = [body.department] + [d for d in e.departments if d != body.department][:2]
    if body.sentiment and e and e.sentiment != body.sentiment:
        changes.append(("sentiment", e.sentiment, body.sentiment))
        e.sentiment = body.sentiment
        e.sentiment_score = {"positive": 0.6, "neutral": 0.0, "negative": -0.6}[body.sentiment]
    if body.message_type and e and e.message_type != body.message_type:
        changes.append(("message_type", e.message_type, body.message_type))
        e.message_type = body.message_type
    if body.status and it.status != body.status:
        changes.append(("status", it.status, body.status))
        set_item_status(it, body.status)
    for field, old, new in changes:
        db.add(Correction(item_id=it.id, field=field, old_value=old, new_value=new, comment=body.comment, user_id=user.id))
    if e and any(c[0] in ("department", "sentiment", "message_type") for c in changes):
        e.reviewed, e.needs_review, e.reviewed_by, e.reviewed_at = True, False, user.id, utcnow()
    audit(db, user, "item.correct", "item", it.id, changes=[{"field": c[0], "old": c[1], "new": c[2]} for c in changes])
    db.commit()
    return get_item(item_id, db, user)


@router.post("/{item_id}/confirm")
def confirm_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    """Operator accepts the AI result as is (human in the loop, 5.4)."""
    it = _get_visible(db, item_id, user)
    if not it.enrichment:
        raise HTTPException(400, "Обращение ещё не проанализировано")
    e = it.enrichment
    e.reviewed, e.needs_review, e.reviewed_by, e.reviewed_at = True, False, user.id, utcnow()
    audit(db, user, "item.confirm", "item", it.id)
    db.commit()
    return {"ok": True}


@router.post("/{item_id}/reanalyze")
def reanalyze(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    from app.pipeline import _apply, _departments, _examples

    it = _get_visible(db, item_id, user)
    outcome = llm.enrich(it.text_masked, _departments(db), _examples(db))
    _apply(it, outcome, get_settings().review_confidence_threshold)
    audit(db, user, "item.reanalyze", "item", it.id, model=outcome.model)
    db.commit()
    return get_item(item_id, db, user)


class Reply(BaseModel):
    text: str = Field(min_length=2, max_length=2000)


@router.post("/{item_id}/reply")
def reply(item_id: int, body: Reply, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    """Reply to a Direct message. Sent only on explicit operator action (3.7.5)."""
    from app.collectors.telegram_bot import send_message

    it = _get_visible(db, item_id, user)
    if not it.is_direct or not it.reply_ref:
        raise HTTPException(400, "Ответ возможен только на личные обращения из Telegram-бота")
    try:
        send_message(it.reply_ref["chat_id"], body.text)
    except Exception as e:
        raise HTTPException(502, f"Не удалось отправить ответ: {e}")
    audit(db, user, "direct.reply", "item", it.id, length=len(body.text))
    if it.status == "new":
        set_item_status(it, "in_progress")
    db.commit()
    return {"ok": True}


@router.delete("/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    """Deletion on request (spec 5.6): removes the item, its analysis and cluster links."""
    it = db.get(Item, item_id)
    if it is None:
        raise HTTPException(404, "Обращение не найдено")
    audit(db, user, "item.delete", "item", it.id, source_id=it.source_id, direct=it.is_direct)
    db.delete(it)
    db.commit()
    return {"ok": True}


class GeoDecision(BaseModel):
    status: Literal["local", "not_local"]
    comment: str | None = Field(None, max_length=500)


@router.post("/{item_id}/geo")
def decide_geo(item_id: int, body: GeoDecision, db: Session = Depends(get_db),
               user: User = Depends(require_role("operator"))):
    """Operator resolves the 'possibly Pavlodar' queue. A local decision brings the item into analytics."""
    from app.pipeline import _apply, _departments, _examples, llm_context

    it = _get_visible(db, item_id, user)
    old = it.geo_status
    it.geo_status, it.geo_reviewed = body.status, True
    it.geo_reason = ("Решение оператора: " + ("относится к Павлодару" if body.status == "local" else "не относится к Павлодару")
                     + (f" ({body.comment})" if body.comment else ""))
    db.add(Correction(item_id=it.id, field="geo", old_value=old, new_value=body.status, comment=body.comment, user_id=user.id))
    if body.status == "local" and it.enrichment is None and not it.is_spam and not it.duplicate_of_id:
        _apply(it, llm.enrich(it.text_masked, _departments(db), _examples(db), llm_context(it)),
               get_settings().review_confidence_threshold)
        it.geo_status, it.geo_reviewed = "local", True
    audit(db, user, "item.geo", "item", it.id, old=old, new=body.status)
    db.commit()
    return get_item(item_id, db, user)
