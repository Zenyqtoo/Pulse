"""One filter object shared by the feed, dashboards, drill-down and exports (spec 3.8.1)."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Query
from sqlalchemy import Select, and_, exists, or_, select

from app.models import Cluster, ClusterItem, Enrichment, Item, Source, User


@dataclass
class Filters:
    date_from: datetime | None = None
    date_to: datetime | None = None
    days: int | None = None
    source_ids: list[int] | None = None
    departments: list[str] | None = None
    sentiments: list[str] | None = None
    priorities: list[str] | None = None
    statuses: list[str] | None = None
    types: list[str] | None = None
    districts: list[str] | None = None
    langs: list[str] | None = None
    q: str | None = None
    cluster_id: int | None = None
    is_direct: bool | None = None
    needs_review: bool | None = None
    urgent: bool | None = None
    origin: str | None = None          # real | synthetic
    include_spam: bool = False
    platforms: list[str] | None = None
    geo: str | None = None             # local (default) | possible | not_local | all
    voice: str | None = None           # resident | media

    def period(self) -> tuple[datetime | None, datetime | None]:
        if self.days and not self.date_from:
            return datetime.now(timezone.utc) - timedelta(days=self.days), self.date_to
        return self.date_from, self.date_to


def _split(v: str | None) -> list[str] | None:
    if not v:
        return None
    parts = [p.strip() for p in v.split(",") if p.strip()]
    return parts or None


def filters_dep(
    date_from: datetime | None = None, date_to: datetime | None = None, days: int | None = Query(None, ge=1, le=3650),
    source: str | None = None, department: str | None = None, sentiment: str | None = None,
    priority: str | None = None, status: str | None = None, type: str | None = None, district: str | None = None,
    lang: str | None = None, q: str | None = Query(None, max_length=200), cluster_id: int | None = None,
    is_direct: bool | None = None, needs_review: bool | None = None, urgent: bool | None = None,
    origin: str | None = Query(None, pattern="^(real|synthetic)$"), include_spam: bool = False,
    platform: str | None = None, geo: str | None = Query(None, pattern="^(local|possible|not_local|all)$"),
    voice: str | None = Query(None, pattern="^(resident|media)$"),
) -> Filters:
    src = _split(source)
    return Filters(
        date_from=date_from, date_to=date_to, days=days,
        source_ids=[int(s) for s in src if s.isdigit()] if src else None,
        departments=_split(department), sentiments=_split(sentiment), priorities=_split(priority),
        statuses=_split(status), types=_split(type), districts=_split(district), langs=_split(lang),
        q=q.strip() if q else None, cluster_id=cluster_id, is_direct=is_direct, needs_review=needs_review,
        urgent=urgent, origin=origin, include_spam=include_spam, platforms=_split(platform), geo=geo, voice=voice,
    )


def resident_condition():
    """SQL twin of serializers.voice() == 'resident': messages of residents, not news or official posts."""
    resident_sources = select(Source.id).where(Source.type.in_(["demo", "upload", "threads"]))
    return or_(Item.is_direct.is_(True), Item.kind.in_(["comment", "reply", "message", "review"]),
               Item.source_id.in_(resident_sources))


def scope_departments(f: Filters, user: User) -> Filters:
    """Department staff see only their sphere (spec 3.8.6)."""
    if user.department_code:
        f.departments = [user.department_code]
    return f


def apply_item_filters(stmt: Select, f: Filters, user: User, analytics: bool = True) -> Select:
    """stmt must select from Item joined with Enrichment."""
    conds = []
    start, end = f.period()
    if start:
        conds.append(Item.published_at >= start)
    if end:
        conds.append(Item.published_at <= end)
    if f.source_ids:
        conds.append(Item.source_id.in_(f.source_ids))
    if f.departments:
        conds.append(Enrichment.primary_department.in_(f.departments))
    if f.sentiments:
        conds.append(Enrichment.sentiment.in_(f.sentiments))
    if f.statuses:
        conds.append(Item.status.in_(f.statuses))
    if f.types:
        conds.append(Enrichment.message_type.in_(f.types))
    if f.districts:
        conds.append(Enrichment.district.in_(f.districts))
    if f.langs:
        conds.append(Item.lang.in_(f.langs))
    if f.q:
        like = f"%{f.q}%"
        conds.append(or_(Item.text_masked.ilike(like), Enrichment.problem_type.ilike(like),
                         Enrichment.district.ilike(like), Enrichment.address.ilike(like)))
    if f.cluster_id:
        conds.append(exists().where(ClusterItem.item_id == Item.id, ClusterItem.cluster_id == f.cluster_id))
    if f.priorities:
        conds.append(exists().where(ClusterItem.item_id == Item.id, ClusterItem.cluster_id == Cluster.id,
                                    Cluster.active.is_(True), Cluster.priority.in_(f.priorities)))
    if f.is_direct is not None:
        conds.append(Item.is_direct.is_(f.is_direct))
    if f.needs_review is not None:
        conds.append(Enrichment.needs_review.is_(f.needs_review))
    if f.urgent:
        conds.append(Enrichment.is_urgent.is_(True))
    if f.origin:
        synthetic = select(Source.id).where(Source.is_synthetic.is_(True))
        conds.append(Item.source_id.in_(synthetic) if f.origin == "synthetic" else Item.source_id.not_in(synthetic))
    if f.platforms:
        conds.append(Item.platform.in_(f.platforms))
    if f.voice:
        conds.append(resident_condition() if f.voice == "resident" else ~resident_condition())
    # Only messages about the monitored city enter analytics unless another geo view is asked for
    if f.geo != "all":
        conds.append(Item.geo_status == (f.geo or "local"))
    if not f.include_spam:
        conds.append(Item.is_spam.is_(False))
        conds.append(Item.duplicate_of_id.is_(None))
    if user.role == "viewer":
        # Direct messages are visible to authorised roles only; viewers get aggregates (3.7.4)
        if not analytics:
            conds.append(Item.is_direct.is_(False))
    if user.department_code:
        conds.append(Enrichment.primary_department == user.department_code)
    return stmt.where(and_(*conds)) if conds else stmt


def base_items() -> Select:
    return select(Item).join(Enrichment, Enrichment.item_id == Item.id)
