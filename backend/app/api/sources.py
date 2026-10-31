import json
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import pipeline
from app.audit import audit
from app.collectors.base import CollectorError
from app.collectors.registry import COLLECTORS, PLATFORM_NAMES, PLATFORM_OF, describe
from app.collectors.upload import parse_upload
from app.db import SessionLocal, get_db
from app.models import CollectionRun, Item, Source, User
from app.security import get_current_user, require_role

router = APIRouter(prefix="/api", tags=["sources"])
_busy = threading.Event()


RECOMMENDED = Path(__file__).resolve().parent.parent / "data" / "pavlodar_sources.json"
GeoScope = Literal["city", "region", "national", "unknown"]


def load_recommended() -> list[dict]:
    return json.loads(RECOMMENDED.read_text(encoding="utf-8"))


def connection_status(s: Source) -> str:
    if not s.enabled:
        return "disabled"
    if s.type not in COLLECTORS:
        return "manual"
    if s.last_status == "error":
        return "error"
    if s.last_status == "ok":
        return "warning" if s.last_error else "ok"
    return "never"


def source_dict(s: Source, counts: dict[int, int], local: dict[int, int] | None = None) -> dict:
    return {"id": s.id, "type": s.type, "name": s.name, "config": s.config, "enabled": s.enabled,
            "is_synthetic": s.is_synthetic, "schedule_minutes": s.schedule_minutes,
            "platform": s.platform, "platform_name": PLATFORM_NAMES.get(s.platform, s.platform),
            "url": s.url, "description": s.description, "geo_scope": s.geo_scope, "recommended_key": s.recommended_key,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
            "last_status": s.last_status, "last_error": s.last_error, "items": counts.get(s.id, 0),
            "local_items": (local or {}).get(s.id, 0), "connection": connection_status(s),
            "auto": s.type in COLLECTORS}


@router.get("/collectors")
def collectors(user: User = Depends(get_current_user)):
    return describe()


def _counts(db: Session) -> tuple[dict, dict]:
    counts = dict(db.execute(select(Item.source_id, func.count()).group_by(Item.source_id)).all())
    local = dict(db.execute(select(Item.source_id, func.count()).where(Item.geo_status == "local")
                            .group_by(Item.source_id)).all())
    return counts, local


@router.get("/sources")
def list_sources(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    counts, local = _counts(db)
    return [source_dict(s, counts, local) for s in db.scalars(select(Source).order_by(Source.id)).all()]


class SourceIn(BaseModel):
    type: str
    name: str = Field(min_length=2, max_length=200)
    config: dict = {}
    enabled: bool = True
    schedule_minutes: int = Field(60, ge=5, le=1440)
    url: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=2000)
    geo_scope: GeoScope = "unknown"


@router.post("/sources")
def create_source(body: SourceIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    if body.type not in COLLECTORS and body.type != "upload":
        raise HTTPException(400, "Неизвестный тип источника")
    s = Source(type=body.type, name=body.name, config=body.config, enabled=body.enabled,
               schedule_minutes=body.schedule_minutes, is_synthetic=body.type == "demo",
               platform=PLATFORM_OF.get(body.type, "other"), url=body.url, description=body.description,
               geo_scope=body.geo_scope)
    db.add(s)
    db.flush()
    audit(db, user, "source.create", "source", s.id, name=body.name, type=body.type)
    db.commit()
    return source_dict(s, {})


@router.get("/sources/recommended")
def recommended(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    added = {s.recommended_key: s.id for s in db.scalars(select(Source).where(Source.recommended_key.is_not(None))).all()}
    return [dict(r, added_source_id=added.get(r["key"])) for r in load_recommended()]


@router.post("/sources/recommended/{key}")
def add_recommended(key: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    rec = next((r for r in load_recommended() if r["key"] == key), None)
    if rec is None:
        raise HTTPException(404, "Рекомендация не найдена")
    if db.scalar(select(Source).where(Source.recommended_key == key)):
        raise HTTPException(409, "Этот источник уже добавлен")
    s = Source(type=rec["type"], name=rec["name"], config=rec["config"], platform=rec["platform"], url=rec["url"],
               description=rec["description"], geo_scope=rec["geo_scope"], recommended_key=key,
               enabled=rec["collection"] in ("accessible", "check_on_first_run"), schedule_minutes=60)
    db.add(s)
    db.flush()
    audit(db, user, "source.create", "source", s.id, name=s.name, recommended=key)
    db.commit()
    return source_dict(s, {})


class SourcePatch(BaseModel):
    name: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    schedule_minutes: int | None = Field(None, ge=5, le=1440)
    url: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=2000)
    geo_scope: GeoScope | None = None


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: SourcePatch, db: Session = Depends(get_db),
                  user: User = Depends(require_role("admin"))):
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "Источник не найден")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    audit(db, user, "source.update", "source", s.id, **body.model_dump(exclude_none=True, exclude={"config", "description"}))
    db.commit()
    counts, local = _counts(db)
    return source_dict(s, counts, local)


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "Источник не найден")
    audit(db, user, "source.delete", "source", s.id, name=s.name)
    db.delete(s)
    db.commit()
    return {"ok": True}


def _background(fn, *args):
    def run():
        db = SessionLocal()
        try:
            fn(db, *args)
        finally:
            db.close()
            _busy.clear()
    _busy.set()
    threading.Thread(target=run, daemon=True).start()


def _run_and_process(db: Session, source_id: int):
    s = db.get(Source, source_id)
    pipeline.run_source(db, s, "manual")
    if pipeline.process_pending(db).get("processed"):
        pipeline.after_processing(db)


def _process_all(db: Session):
    if pipeline.process_pending(db, limit=2000).get("processed") is not None:
        pipeline.after_processing(db)


@router.post("/sources/{source_id}/run")
def run_now(source_id: int, db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    """'Collect now' (3.1.4). Runs in the background; the UI polls /api/runs."""
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "Источник не найден")
    if s.type not in COLLECTORS:
        raise HTTPException(400, "Этот источник пополняется загрузкой файлов")
    if _busy.is_set():
        raise HTTPException(409, "Сбор уже выполняется, подождите")
    audit(db, user, "source.run", "source", s.id)
    db.commit()
    _background(_run_and_process, source_id)
    return {"started": True}


@router.post("/pipeline/process")
def process_now(db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    if _busy.is_set():
        raise HTTPException(409, "Обработка уже выполняется")
    audit(db, user, "pipeline.process")
    db.commit()
    _background(_process_all)
    return {"started": True}


@router.get("/pipeline/status")
def pipeline_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    pending = db.scalar(select(func.count()).select_from(Item).where(Item.process_state == "pending"))
    return {"busy": _busy.is_set(), "pending": pending}


@router.get("/runs")
def runs(limit: int = 50, source_id: int | None = None, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    stmt = select(CollectionRun, Source.name).join(Source, Source.id == CollectionRun.source_id)
    if source_id:
        stmt = stmt.where(CollectionRun.source_id == source_id)
    rows = db.execute(stmt.order_by(CollectionRun.started_at.desc()).limit(min(limit, 500))).all()
    return [{"id": r.id, "source_id": r.source_id, "source": name, "trigger": r.trigger,
             "started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
             "status": r.status, "fetched": r.fetched, "new_items": r.new_items, "duplicates": r.duplicates,
             "spam": r.spam, "not_local": r.not_local, "error": r.error} for r, name in rows]


@router.post("/upload")
async def upload(file: UploadFile = File(...), source_name: str = Form("Загрузка файлов"),
                 geo_scope: str = Form("unknown"),
                 db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    if geo_scope not in ("city", "region", "national", "unknown"):
        raise HTTPException(400, "Неверный географический охват")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 20 МБ")
    try:
        items, warnings = parse_upload(file.filename or "upload.csv", data)
    except CollectorError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Не удалось прочитать файл: {e}")
    name = source_name.strip()[:200] or "Загрузка файлов"
    src = db.scalar(select(Source).where(Source.type == "upload", Source.name == name))
    if src is None:
        src = Source(type="upload", name=name, config={}, enabled=True, platform="upload", geo_scope=geo_scope,
                     description=f"Файл {file.filename}")
        db.add(src)
        db.flush()
    run = pipeline.ingest(db, src, items, trigger="upload")
    if warnings:
        run.error = "; ".join(warnings)
    src.last_run_at, src.last_status = run.finished_at, "ok"
    audit(db, user, "source.upload", "source", src.id, filename=file.filename, rows=len(items), new=run.new_items)
    db.commit()
    if not _busy.is_set():
        _background(_process_all)
    return {"source_id": src.id, "rows": len(items), "new_items": run.new_items, "duplicates": run.duplicates,
            "spam": run.spam, "not_local": run.not_local, "warnings": warnings}
