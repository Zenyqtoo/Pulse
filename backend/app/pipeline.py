"""Ingestion and processing pipeline.

collect → normalise + exact dedup + PII masking + spam pre-filter (ingest)
        → near-duplicate check + one LLM call per item (process_pending)
        → re-cluster + priorities + alerts (after_processing)
"""
import hashlib
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import geo
from app.ai import clustering, embeddings, llm, rules
from app.ai.lang import detect_language
from app.ai.masking import mask_extra_names, mask_pii
from app.collectors.base import CollectorError, RawItem
from app.collectors.registry import COLLECTORS
from app.config import get_settings
from app.models import (AppState, CollectionRun, Correction, Department, Enrichment, GoldLabel, Item, Source,
                        utcnow)
from app.security import author_hash

log = logging.getLogger("pulse.pipeline")
_lock = threading.Lock()   # one processing run at a time
_URL = re.compile(r"https?://\S+|www\.\S+")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalise(text: str) -> str:
    t = _URL.sub(" ", (text or "").lower().replace("ё", "е"))
    t = _NON_WORD.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalise(text).encode()).hexdigest()


def ingest(db: Session, source: Source, raw: list[RawItem], trigger: str = "schedule") -> CollectionRun:
    run = CollectionRun(source_id=source.id, trigger=trigger, fetched=len(raw), new_items=0, duplicates=0, spam=0,
                        not_local=0)
    db.add(run)
    existing_ext = set(db.scalars(select(Item.external_id).where(Item.source_id == source.id,
                                                                 Item.external_id.in_([r.external_id for r in raw]))).all()) if raw else set()
    hashes = {r_hash: item_id for r_hash, item_id in db.execute(
        select(Item.content_hash, Item.id).where(Item.duplicate_of_id.is_(None),
                                                 Item.content_hash.in_([content_hash(r.text) for r in raw])))} if raw else {}
    for r in raw:
        if r.external_id in existing_ext:
            continue
        existing_ext.add(r.external_id)
        h = content_hash(r.text)
        masked, pii = mask_pii(r.text, strict_address=r.is_direct)
        is_spam, reason = rules.spam_check(r.text)
        context_masked = mask_pii(r.context_text)[0][:1500] if r.context_text else None
        scope = "city" if (r.is_direct and source.geo_scope == "unknown") else source.geo_scope
        g = geo.classify_rules(masked, scope, context_masked)
        item = Item(
            source_id=source.id, external_id=r.external_id, url=r.url, text=r.text, text_masked=masked,
            pii_found=pii, lang=detect_language(r.text), published_at=r.published_at,
            author_hash=author_hash(r.platform, r.author_id), reactions=r.reactions, replies=r.replies,
            views=r.views, is_direct=r.is_direct or source.type == "telegram_bot", content_hash=h,
            is_spam=is_spam, spam_reason=reason, reply_ref=r.extra.get("reply_ref"),
            platform=source.platform, kind=r.kind, parent_external_id=r.parent_external_id, parent_url=r.parent_url,
            context_text=context_masked, geo_status=g.status, geo_score=g.score, geo_reason=g.reason,
            geo_evidence=g.evidence,
        )
        if h in hashes:
            item.duplicate_of_id = hashes[h]
            item.process_state = "done"
            run.duplicates += 1
        elif is_spam:
            item.process_state = "done"
            run.spam += 1
        elif g.certain and g.status == "not_local":
            item.process_state = "done"     # clearly about another place: never sent to the LLM
            run.not_local += 1
        db.add(item)
        db.flush()
        if not item.duplicate_of_id:
            hashes.setdefault(h, item.id)
        run.new_items += 1
    run.finished_at = utcnow()
    run.status = "ok"
    db.commit()
    return run


def run_source(db: Session, source: Source, trigger: str = "schedule") -> CollectionRun:
    """Fetch one source and ingest. Errors are recorded on the run and the source, never raised."""
    cls = COLLECTORS.get(source.type)
    started = utcnow()
    if cls is None:
        run = CollectionRun(source_id=source.id, trigger=trigger, status="error", finished_at=utcnow(),
                            error=f"Тип источника «{source.type}» не собирается автоматически")
        db.add(run)
        db.commit()
        return run
    collector = cls(source.config)
    if getattr(cls, "needs_credentials", None):
        from app.integrations import tokens
        collector.credential = tokens.load(db, cls.needs_credentials)
    state_key = f"source:{source.id}"
    state_row = db.get(AppState, state_key)
    collector.state = dict(state_row.value) if state_row else {}
    since = source.last_run_at - timedelta(hours=6) if source.last_run_at and source.last_status == "ok" else None
    try:
        raw = collector.fetch(since)
        run = ingest(db, source, raw, trigger)
        run.started_at = started
        if collector.warnings:
            run.error = "; ".join(collector.warnings)[:2000]
        source.last_status, source.last_error = "ok", run.error
        source.last_success_at = utcnow()
    except CollectorError as e:
        db.rollback()
        run = CollectionRun(source_id=source.id, trigger=trigger, status="error", started_at=started,
                            finished_at=utcnow(), error=str(e)[:2000])
        db.add(run)
        source.last_status, source.last_error = "error", str(e)[:2000]
    except Exception as e:  # unexpected: keep the app alive, record it
        db.rollback()
        log.exception("collector %s failed", source.name)
        run = CollectionRun(source_id=source.id, trigger=trigger, status="error", started_at=started,
                            finished_at=utcnow(), error=f"{type(e).__name__}: {e}"[:2000])
        db.add(run)
        source.last_status, source.last_error = "error", run.error
    source.last_run_at = utcnow()
    if getattr(collector, "state", None):
        if state_row:
            state_row.value = collector.state
        else:
            db.add(AppState(key=state_key, value=collector.state))
    db.commit()
    return run


def _departments(db: Session) -> list[dict]:
    return [{"code": d.code, "name": d.name, "description": d.description, "keywords": d.keywords or []}
            for d in db.scalars(select(Department).order_by(Department.sort)).all()]


def _examples(db: Session) -> list[dict]:
    """Recent operator corrections become few-shot examples (spec 3.2.5)."""
    test_ids = select(GoldLabel.item_id).where(GoldLabel.split == "test")  # never leak the test set
    rows = db.execute(
        select(Correction, Item).join(Item, Item.id == Correction.item_id)
        .where(Correction.field.in_(["department", "sentiment"]), Item.id.not_in(test_ids))
        .order_by(Correction.created_at.desc()).limit(12)
    ).all()
    return [{"text": it.text_masked, "label": f"{c.field} = {c.new_value}"} for c, it in rows]


def _mark_near_duplicates(db: Session, pending: list[Item]) -> None:
    """Reposts with slightly different text: cosine ≥ 0.92 within 48 h counts as a duplicate."""
    if not pending:
        return
    since = min(i.published_at for i in pending) - timedelta(hours=48)
    recent = db.scalars(select(Item).where(Item.process_state == "done", Item.duplicate_of_id.is_(None),
                                           Item.is_spam.is_(False), Item.published_at >= since).limit(3000)).all()
    pool = recent + pending
    if len(pool) < 2:
        return
    vecs = embeddings.embed([normalise(i.text_masked) for i in pool])
    n_recent = len(recent)
    for pi, item in enumerate(pending, start=n_recent):
        if len(normalise(item.text_masked)) < 25:
            continue
        sims = vecs[:pi] @ vecs[pi]
        if len(sims) and float(np.max(sims)) >= 0.92:
            j = int(np.argmax(sims))
            original = pool[j]
            if original.duplicate_of_id is None and original.id != item.id:
                item.duplicate_of_id = original.id
                item.process_state = "done"


def _apply(item: Item, outcome: llm.EnrichOutcome, threshold: float) -> None:
    r = outcome.result
    masked, extra = mask_extra_names(item.text_masked, r.pii_names)
    if extra:
        item.text_masked = masked
        item.pii_found = sorted(set(item.pii_found or []) | {"name"})
    e = item.enrichment or Enrichment(item_id=item.id)
    e.departments = r.departments
    e.primary_department = r.primary_department
    e.dept_confidence = round(r.department_confidence, 3)
    e.sentiment = r.sentiment
    e.sentiment_score = round(r.sentiment_score, 3)
    e.sentiment_confidence = round(r.sentiment_confidence, 3)
    e.message_type = r.message_type
    e.district = rules.normalize_district(r.entities.district, item.text_masked)
    e.address = r.entities.address
    e.object = r.entities.object
    e.problem_type = r.entities.problem_type
    e.urgency_markers = r.urgency_markers
    e.is_urgent = bool(r.urgency_markers)
    e.rationale = r.rationale
    e.model_department = r.primary_department
    e.model_departments = r.departments
    e.model_sentiment = r.sentiment
    e.model_message_type = r.message_type
    e.reviewed = False
    e.model = outcome.model
    e.prompt_version = get_settings().prompt_version if not outcome.model.startswith("rules") else "rules-v1"
    e.latency_ms = outcome.latency_ms
    e.needs_review = r.department_confidence < threshold and not e.reviewed
    e.created_at = utcnow()
    item.enrichment = e
    if r.is_spam and not item.is_spam:
        item.is_spam = True
        item.spam_reason = (r.spam_reason or "модель: спам")[:200]
    e.geo_relevance = r.geo.relevance if r.geo else None
    e.place_mentioned = (r.geo.place or None) if r.geo else None
    if not item.geo_reviewed:   # an operator's geo decision always wins
        apply_geo(item, r.geo.relevance if r.geo else None, r.geo.reason if r.geo else None)
    item.process_state = "done"
    item.process_error = outcome.error


def item_scope(item: Item) -> str:
    scope = item.source.geo_scope if item.source else "unknown"
    return "city" if (item.is_direct and scope == "unknown") else scope


def apply_geo(item: Item, llm_relevance: str | None = None, llm_reason: str | None = None) -> None:
    scope = item_scope(item)
    rules_result = geo.classify_rules(item.text_masked, scope, item.context_text)
    final = geo.combine(rules_result, llm_relevance, llm_reason, scope)
    item.geo_status, item.geo_score, item.geo_reason, item.geo_evidence = (
        final.status, round(final.score, 2), final.reason, final.evidence)


SCOPE_TEXT = {"city": "посвящён городу", "region": "о Павлодарской области", "national": "общенациональный",
              "unknown": "охват не указан"}


def llm_context(item: Item) -> dict:
    src = item.source
    desc = f"{src.name} ({src.platform}; {SCOPE_TEXT.get(item_scope(item), '')})" if src else None
    if src and src.description:
        desc += f". {src.description[:200]}"
    return {"source": desc, "platform": item.platform, "kind": item.kind, "parent_text": item.context_text}


def process_pending(db: Session, limit: int = 500) -> dict:
    """Enrich pending items in parallel. Safe to call repeatedly."""
    if not _lock.acquire(blocking=False):
        return {"skipped": "already running"}
    try:
        s = get_settings()
        pending = db.scalars(select(Item).where(Item.process_state.in_(["pending", "error"]))
                             .order_by(Item.is_direct.desc(), Item.published_at.desc()).limit(limit)).all()
        if not pending:
            return {"processed": 0}
        _mark_near_duplicates(db, [p for p in pending if not p.is_spam])
        todo = [p for p in pending if p.process_state != "done"]
        depts, examples = _departments(db), _examples(db)
        texts = {p.id: (p.text_masked, llm_context(p)) for p in todo}

        def work(item_id: int):
            try:
                text, ctx = texts[item_id]
                return item_id, llm.enrich(text, depts, examples, ctx), None
            except Exception as e:  # defensive: never lose the batch
                return item_id, None, f"{type(e).__name__}: {e}"

        by_id = {p.id: p for p in todo}
        with ThreadPoolExecutor(max_workers=max(1, s.llm_parallelism)) as pool:
            results = list(pool.map(work, list(by_id)))
        failed = 0
        for item_id, outcome, err in results:
            item = by_id[item_id]
            if outcome is None:
                item.process_state, item.process_error = "error", err
                failed += 1
                continue
            _apply(item, outcome, s.review_confidence_threshold)
        db.commit()
        return {"processed": len(todo) - failed, "failed": failed,
                "duplicates": sum(1 for p in pending if p.duplicate_of_id)}
    finally:
        _lock.release()


def after_processing(db: Session) -> dict:
    stats = clustering.recluster(db)
    try:
        from app.alerts import send_alerts

        stats["alerts"] = send_alerts(db)
    except Exception as e:
        log.warning("alerts failed: %s", e)
    return stats


def collect_all(db: Session, trigger: str = "schedule", only_due: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    runs = []
    for src in db.scalars(select(Source).where(Source.enabled.is_(True))).all():
        if src.type not in COLLECTORS or src.type in ("demo", "telegram_bot"):   # the bot has its own 20-second job
            continue
        if only_due and src.last_run_at:
            last = src.last_run_at if src.last_run_at.tzinfo else src.last_run_at.replace(tzinfo=timezone.utc)
            if now - last < timedelta(minutes=src.schedule_minutes - 1):
                continue
        runs.append(run_source(db, src, trigger))
    processed = process_pending(db)
    clusters = after_processing(db) if processed.get("processed") else {}
    return {"runs": len(runs), "processed": processed, "clusters": clusters}
