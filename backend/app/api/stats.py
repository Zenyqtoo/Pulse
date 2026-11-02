"""Aggregates for dashboards 1–3 and the operational view. All respect the shared filters and role scope."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.filters import Filters, apply_item_filters, filters_dep, resident_condition
from app.models import Cluster, ClusterItem, Correction, Enrichment, Item, Source, User
from app.collectors.registry import PLATFORM_NAMES
from app.reference import DEPT_NAMES
from app.security import get_current_user
from app.serializers import cluster_dict

router = APIRouter(prefix="/api/stats", tags=["stats"])
SLA_HOURS = 48


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _rows(db: Session, f: Filters, user: User):
    stmt = select(Item.id, Item.published_at, Item.source_id, Item.status, Item.transferred_at, Item.resolved_at,
                  Item.is_direct, Item.lang, Enrichment.primary_department, Enrichment.sentiment,
                  Enrichment.district, Enrichment.message_type, Enrichment.needs_review, Enrichment.is_urgent,
                  Enrichment.sentiment_score, Item.platform).join(Enrichment, Enrichment.item_id == Item.id)
    return db.execute(apply_item_filters(stmt, f, user, analytics=True)).all()


def _high_ids(db: Session) -> set[int]:
    return set(db.scalars(select(ClusterItem.item_id).join(Cluster, Cluster.id == ClusterItem.cluster_id)
                          .where(Cluster.active.is_(True), Cluster.priority == "high")).all())


def _hours(a, b) -> float | None:
    if not a or not b:
        return None
    return max(0.0, (_aware(b) - _aware(a)).total_seconds() / 3600)


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _kpis(rows, high: set[int]) -> dict:
    n = len(rows)
    sent = Counter(r.sentiment for r in rows)
    pos, neg = sent.get("positive", 0), sent.get("negative", 0)
    return {
        "total": n,
        "mood_index": round(100 * (pos - neg) / n, 1) if n else 0,
        "high_priority_share": round(100 * sum(1 for r in rows if r.id in high) / n, 1) if n else 0,
        "review_share": round(100 * sum(1 for r in rows if r.needs_review) / n, 1) if n else 0,
        "resolved_share": round(100 * sum(1 for r in rows if r.status in ("resolved", "closed")) / n, 1) if n else 0,
        "urgent": sum(1 for r in rows if r.is_urgent),
        "direct": sum(1 for r in rows if r.is_direct),
        "avg_hours_to_transfer": _avg([_hours(r.published_at, r.transferred_at) for r in rows]),
        "avg_hours_to_resolve": _avg([_hours(r.published_at, r.resolved_at) for r in rows]),
    }


@router.get("/overview")
def overview(f: Filters = Depends(filters_dep), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not f.days and not f.date_from:
        f.days = 30
    rows = _rows(db, f, user)
    high = _high_ids(db)
    k = _kpis(rows, high)
    # previous period of the same length
    start, end = f.period()
    end = end or datetime.now(timezone.utc)
    prev = None
    if start:
        span = end - start
        pf = Filters(**{**f.__dict__, "days": None, "date_from": start - span, "date_to": start})
        prev_rows = _rows(db, pf, user)
        prev = _kpis(prev_rows, high)
    k["prev_total"] = prev["total"] if prev else None
    k["total_delta_pct"] = round(100 * (k["total"] - prev["total"]) / prev["total"], 1) if prev and prev["total"] else None
    k["mood_delta"] = round(k["mood_index"] - prev["mood_index"], 1) if prev and prev["total"] else None

    daily: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        daily[_aware(r.published_at).date().isoformat()][r.sentiment] += 1
    if start:
        d = start.date()
        while d <= end.date():
            daily.setdefault(d.isoformat(), Counter())
            d += timedelta(days=1)
    sources = {s.id: s for s in db.scalars(select(Source)).all()}
    by_source = Counter(r.source_id for r in rows)
    by_dept: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_dept[r.primary_department][r.sentiment] += 1
    by_district: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.district:
            by_district[r.district][r.sentiment] += 1
    by_platform: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_platform[r.platform][r.sentiment] += 1
    clusters = _top_clusters(db, user, f, limit=5)
    multi = [c for c in _top_clusters(db, user, f, limit=200) if c["multi_platform"]][:6]
    gf = Filters(**{**f.__dict__, "geo": "all"})
    geo_rows = db.execute(apply_item_filters(select(Item.geo_status, func.count()).select_from(Item)
                                             .outerjoin(Enrichment, Enrichment.item_id == Item.id), gf, user, True)
                          .group_by(Item.geo_status)).all()
    hot = [c for c in _top_clusters(db, user, f, limit=50) if c["is_hot"]][:5]
    return {
        "kpis": k,
        "sentiment": {s: sum(1 for r in rows if r.sentiment == s) for s in ("positive", "neutral", "negative")},
        "daily": [{"date": d, "positive": c["positive"], "neutral": c["neutral"], "negative": c["negative"]}
                  for d, c in sorted(daily.items())],
        "by_source": [{"source_id": sid, "name": sources[sid].name if sid in sources else str(sid),
                       "type": sources[sid].type if sid in sources else None,
                       "is_synthetic": sources[sid].is_synthetic if sid in sources else False, "count": n}
                      for sid, n in by_source.most_common()],
        "by_department": sorted([{"code": code, "name": DEPT_NAMES.get(code, code), "count": sum(c.values()),
                                  "positive": c["positive"], "neutral": c["neutral"], "negative": c["negative"]}
                                 for code, c in by_dept.items()], key=lambda x: -x["count"]),
        "by_district": sorted([{"district": dname, "count": sum(c.values()),
                                "negative": c["negative"],
                                "neg_share": round(c["negative"] / sum(c.values()), 2)}
                               for dname, c in by_district.items()], key=lambda x: -x["count"])[:12],
        "by_type": dict(Counter(r.message_type for r in rows)),
        "by_lang": dict(Counter(r.lang or "other" for r in rows)),
        "top_problems": clusters,
        "hot_topics": hot,
        "by_platform": sorted([{"platform": pl, "name": PLATFORM_NAMES.get(pl, pl), "count": sum(c.values()),
                                "positive": c["positive"], "neutral": c["neutral"], "negative": c["negative"]}
                               for pl, c in by_platform.items()], key=lambda x: -x["count"]),
        "multi_platform_problems": multi,
        "geo": {k: v for k, v in geo_rows},
    }


def _top_clusters(db: Session, user: User, f: Filters, limit: int) -> list[dict]:
    stmt = select(Cluster).where(Cluster.active.is_(True))
    # The same global filter as the charts: a problem shows up only if it matches the selection
    stmt = stmt.where(Cluster.status.in_(f.statuses) if f.statuses else Cluster.status.not_in(["resolved", "closed"]))
    if user.department_code:
        stmt = stmt.where(Cluster.department == user.department_code)
    if f.departments:
        stmt = stmt.where(Cluster.department.in_(f.departments))
    if f.priorities:
        stmt = stmt.where(Cluster.priority.in_(f.priorities))
    if f.districts:
        stmt = stmt.where(Cluster.district.in_(f.districts))
    if f.q:
        stmt = stmt.where(or_(Cluster.title.ilike(f"%{f.q}%"), Cluster.summary.ilike(f"%{f.q}%")))
    start, end = f.period()
    if start:
        stmt = stmt.where(Cluster.last_seen >= start)
    if end:
        stmt = stmt.where(Cluster.first_seen <= end)
    if f.urgent:
        stmt = stmt.where(Cluster.has_urgent.is_(True))
    if f.origin:
        from app.api.clusters import origin_condition
        stmt = stmt.where(origin_condition(f.origin))
    if f.platforms:   # problems discussed on at least one of the selected platforms
        stmt = stmt.where(Cluster.id.in_(select(ClusterItem.cluster_id).join(Item, Item.id == ClusterItem.item_id)
                                         .where(Item.platform.in_(f.platforms))))
    return [cluster_dict(c) for c in db.scalars(stmt.order_by(Cluster.priority_score.desc()).limit(limit)).all()]


@router.get("/departments")
def departments(f: Filters = Depends(filters_dep), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not f.days and not f.date_from:
        f.days = 30
    rows = _rows(db, f, user)
    clusters = db.scalars(select(Cluster).where(Cluster.active.is_(True))).all()
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r.primary_department].append(r)
    out = []
    for code, rs in by.items():
        n = len(rs)
        sent = Counter(r.sentiment for r in rs)
        resolved = sum(1 for r in rs if r.status in ("resolved", "closed"))
        transfer = _avg([_hours(r.published_at, r.transferred_at) for r in rs])
        dc = [c for c in clusters if c.department == code]
        neg_share = sent["negative"] / n
        speed = 1.0 if transfer is None else max(0.0, 1 - transfer / (SLA_HOURS * 2))
        rating = round(50 * resolved / n + 30 * (1 - neg_share) + 20 * (speed if transfer is not None else 0), 1)
        out.append({
            "code": code, "name": DEPT_NAMES.get(code, code), "count": n,
            "positive": sent["positive"], "neutral": sent["neutral"], "negative": sent["negative"],
            "mood_index": round(100 * (sent["positive"] - sent["negative"]) / n, 1),
            "resolved_share": round(100 * resolved / n, 1), "avg_hours_to_transfer": transfer,
            "avg_hours_to_resolve": _avg([_hours(r.published_at, r.resolved_at) for r in rs]),
            "open_problems": sum(1 for c in dc if c.status not in ("resolved", "closed")),
            "high_problems": sum(1 for c in dc if c.priority == "high" and c.status not in ("resolved", "closed")),
            "review_share": round(100 * sum(1 for r in rs if r.needs_review) / n, 1),
            "urgent": sum(1 for r in rs if r.is_urgent),
            "rating": rating,
        })
    out.sort(key=lambda x: -x["count"])
    return {"departments": out, "rating_formula": "50·доля решённых + 30·(1 − доля негатива) + 20·скорость передачи (SLA 48 ч)"}


@router.get("/operations")
def operations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    base = select(func.count()).select_from(Item).join(Enrichment, Enrichment.item_id == Item.id) \
        .where(Item.is_spam.is_(False), Item.duplicate_of_id.is_(None))
    if user.department_code:
        base = base.where(Enrichment.primary_department == user.department_code)
    review = db.scalar(base.where(Enrichment.needs_review.is_(True)))
    # News and official posts need no reply, so only residents' messages can be "without reaction"
    overdue = db.scalar(base.where(Item.status == "new", Item.published_at < now - timedelta(hours=SLA_HOURS),
                                   resident_condition()))
    new_direct = db.scalar(base.where(Item.is_direct.is_(True), Item.status == "new"))
    pending = db.scalar(select(func.count()).select_from(Item).where(Item.process_state.in_(["pending", "error"])))
    geo_queue = db.scalar(select(func.count()).select_from(Item).where(
        Item.geo_status == "possible", Item.geo_reviewed.is_(False), Item.is_spam.is_(False), Item.duplicate_of_id.is_(None)))
    errors = db.scalar(select(func.count()).select_from(Item).where(Item.process_state == "error"))
    week = now - timedelta(days=7)
    load = db.execute(select(Correction.user_id, func.count()).where(Correction.created_at >= week)
                      .group_by(Correction.user_id)).all()
    users = {u.id: u.full_name for u in db.scalars(select(User)).all()}
    return {"review_queue": review, "geo_queue": geo_queue, "overdue": overdue, "sla_hours": SLA_HOURS, "new_direct": new_direct,
            "unprocessed": pending, "processing_errors": errors,
            "operator_load": [{"user": users.get(uid, "—"), "actions": n} for uid, n in load]}
