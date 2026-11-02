import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import embeddings
from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.evaluation import evaluate, run_dict, split_for
from app.models import Department, Enrichment, EvalRun, GoldLabel, Item, Source, User
from app.pipeline import _departments
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api/quality", tags=["quality"])


def _scoped(stmt, user: User):
    """Department staff label and export only their own sphere's messages (spec 3.8.6)."""
    if user.department_code:
        stmt = stmt.where(Item.id.in_(select(Enrichment.item_id)
                                      .where(Enrichment.primary_department == user.department_code)))
    return stmt


def _own_item(db: Session, item_id: int, user: User) -> Item:
    it = db.get(Item, item_id)
    if it is None:
        raise HTTPException(404, "Обращение не найдено")
    if user.department_code and (not it.enrichment or it.enrichment.primary_department != user.department_code):
        raise HTTPException(403, "Обращение относится к другому подразделению")
    return it


def _pct(xs: list[int], q: float):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


@router.get("")
def summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = get_settings()
    gold = db.execute(select(GoldLabel.split, Source.is_synthetic, func.count())
                      .join(Item, Item.id == GoldLabel.item_id).join(Source, Source.id == Item.source_id)
                      .group_by(GoldLabel.split, Source.is_synthetic)).all()
    counts = {f"{'synthetic' if syn else 'real'}_{split}": n for split, syn, n in gold}
    lat = [x for (x,) in db.execute(select(Enrichment.latency_ms).where(Enrichment.model.not_like("rules%"),
                                                                       Enrichment.latency_ms.is_not(None))).all()]
    models = dict(db.execute(select(Enrichment.model, func.count()).group_by(Enrichment.model)).all())
    total = db.scalar(select(func.count()).select_from(Enrichment)) or 0
    review = db.scalar(select(func.count()).select_from(Enrichment).where(Enrichment.needs_review.is_(True))) or 0
    corrected = db.scalar(select(func.count()).select_from(Enrichment).where(
        Enrichment.reviewed.is_(True), Enrichment.model_department != Enrichment.primary_department)) or 0
    runs = db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(10)).all()
    return {
        "llm_enabled": s.llm_enabled, "llm_model": s.llm_model_enrich, "summary_model": s.llm_model_summary,
        "prompt_version": s.prompt_version, "embedding_backend": embeddings.backend_name(),
        "review_threshold": s.review_confidence_threshold,
        "gold_counts": counts, "models": models, "analysed": total,
        "review_share": round(100 * review / total, 1) if total else 0, "corrected_departments": corrected,
        "latency_ms": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "n": len(lat)},
        "runs": [run_dict(r) for r in runs],
    }


class EvalIn(BaseModel):
    split: Literal["test", "dev", "all"] = "test"
    origin: Literal["real", "synthetic", "all"] = "real"
    mode: Literal["stored", "rerun"] = "stored"


@router.post("/evaluate")
def run_eval(body: EvalIn, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    run = evaluate(db, body.split, body.origin, body.mode, _departments(db))
    audit(db, user, "quality.evaluate", "eval_run", run.id, n=run.n, split=body.split, origin=body.origin)
    db.commit()
    if run.n == 0:
        raise HTTPException(400, "Нет размеченных обращений для выбранного набора. Разметьте обращения на вкладке «Разметка».")
    return run_dict(run)


@router.get("/labeling")
def labeling_queue(origin: Literal["real", "synthetic", "all"] = "real", limit: int = Query(20, le=100),
                   db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    """Blind labelling: returns masked text only, never the AI prediction."""
    stmt = (select(Item).join(Source, Source.id == Item.source_id).join(Enrichment, Enrichment.item_id == Item.id)
            .where(Item.is_spam.is_(False), Item.duplicate_of_id.is_(None),
                   Item.id.not_in(select(GoldLabel.item_id))))
    if origin == "real":
        stmt = stmt.where(Source.is_synthetic.is_(False))
    elif origin == "synthetic":
        stmt = stmt.where(Source.is_synthetic.is_(True))
    stmt = _scoped(stmt, user)
    rows = db.scalars(stmt.order_by(func.random()).limit(limit)).all()
    left = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {"remaining": left, "items": [{"id": i.id, "text": i.text_masked, "lang": i.lang,
                                          "source": i.source.name, "is_synthetic": i.source.is_synthetic} for i in rows]}


class GoldIn(BaseModel):
    department: str
    sentiment: Literal["positive", "neutral", "negative"]


@router.put("/gold/{item_id}")
def set_gold(item_id: int, body: GoldIn, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    _own_item(db, item_id, user)
    if not db.scalar(select(Department.id).where(Department.code == body.department)):
        raise HTTPException(400, "Неизвестное подразделение")
    g = db.get(GoldLabel, item_id) or GoldLabel(item_id=item_id, split=split_for(item_id))
    g.department, g.sentiment, g.labeled_by = body.department, body.sentiment, user.id
    db.add(g)
    audit(db, user, "gold.label", "item", item_id)
    db.commit()
    return {"item_id": item_id, "split": g.split}


@router.delete("/gold/{item_id}")
def delete_gold(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    _own_item(db, item_id, user)
    g = db.get(GoldLabel, item_id)
    if g:
        db.delete(g)
        db.commit()
    return {"ok": True}


@router.get("/gold/export")
def export_gold(db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    rows = db.execute(_scoped(select(GoldLabel, Item, Source).join(Item, Item.id == GoldLabel.item_id)
                              .join(Source, Source.id == Item.source_id), user)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["item_id", "split", "origin", "department", "sentiment", "text_masked"])
    for g, it, src in rows:
        w.writerow([it.id, g.split, "synthetic" if src.is_synthetic else "real", g.department, g.sentiment, it.text_masked])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=gold_labels.csv"})


@router.post("/gold/import")
async def import_gold(file: UploadFile = File(...), db: Session = Depends(get_db),
                      user: User = Depends(require_role("operator"))):
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    codes = set(db.scalars(select(Department.code)).all())
    n = 0
    for row in reader:
        try:
            iid = int(row["item_id"])
        except (KeyError, ValueError):
            continue
        if row.get("department") not in codes or row.get("sentiment") not in ("positive", "neutral", "negative"):
            continue
        it = db.get(Item, iid)
        if not it or (user.department_code and (not it.enrichment
                                                or it.enrichment.primary_department != user.department_code)):
            continue
        g = db.get(GoldLabel, iid) or GoldLabel(item_id=iid, split=split_for(iid))
        g.department, g.sentiment, g.labeled_by = row["department"], row["sentiment"], user.id
        db.add(g)
        n += 1
    audit(db, user, "gold.import", rows=n)
    db.commit()
    return {"imported": n}
