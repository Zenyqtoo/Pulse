from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.ai import clustering
from app.api.items import set_item_status
from app.audit import audit
from app.db import get_db
from app.models import Cluster, ClusterItem, Department, Item, User, utcnow
from app.security import get_current_user, require_role
from app.serializers import cluster_dict, item_dict

router = APIRouter(prefix="/api/clusters", tags=["clusters"])

SORTS = {"priority": Cluster.priority_score.desc(), "count": Cluster.item_count.desc(),
         "growth": Cluster.count_24h.desc(), "recent": Cluster.last_seen.desc()}


def cluster_query(user: User, department: str | None = None, priority: str | None = None,
                  status: str | None = None, district: str | None = None, q: str | None = None,
                  hot: bool | None = None, include_inactive: bool = False, platform: str | None = None,
                  multi: bool | None = None):
    stmt = select(Cluster)
    if not include_inactive:
        stmt = stmt.where(Cluster.active.is_(True))
    if user.department_code:
        stmt = stmt.where(Cluster.department == user.department_code)
    if department:
        stmt = stmt.where(Cluster.department.in_(department.split(",")))
    if priority:
        stmt = stmt.where(Cluster.priority.in_(priority.split(",")))
    if status:
        stmt = stmt.where(Cluster.status.in_(status.split(",")))
    if district:
        stmt = stmt.where(Cluster.district == district)
    if q:
        stmt = stmt.where(or_(Cluster.title.ilike(f"%{q}%"), Cluster.summary.ilike(f"%{q}%")))
    if hot:
        stmt = stmt.where(Cluster.count_24h >= 3, Cluster.growth_rate >= 1.5)
    if platform:
        stmt = stmt.where(Cluster.id.in_(select(ClusterItem.cluster_id).join(Item, Item.id == ClusterItem.item_id)
                                         .where(Item.platform.in_(platform.split(",")))))
    if multi:
        stmt = stmt.where(func.json_array_length(Cluster.platforms) > 1)
    return stmt


@router.get("")
def list_clusters(department: str | None = None, priority: str | None = None, status: str | None = None,
                  district: str | None = None, q: str | None = Query(None, max_length=200), hot: bool | None = None,
                  platform: str | None = None, multi: bool | None = None, sort: str = "priority", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = cluster_query(user, department, priority, status, district, q, hot, platform=platform, multi=multi)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(SORTS.get(sort, SORTS["priority"]), Cluster.id.desc())
                      .limit(page_size).offset((page - 1) * page_size)).all()
    return {"total": total, "items": [cluster_dict(c) for c in rows]}


@router.get("/{cluster_id}")
def get_cluster(cluster_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Cluster, cluster_id, options=[joinedload(Cluster.members).joinedload(ClusterItem.item)
                                             .joinedload(Item.enrichment)])
    if c is None:
        raise HTTPException(404, "Проблема не найдена")
    if user.department_code and c.department != user.department_code:
        raise HTTPException(403, "Проблема относится к другому подразделению")
    members = sorted(c.members, key=lambda m: m.item.published_at, reverse=True)
    visible = [m for m in members if not (m.item.is_direct and user.role == "viewer")]
    d = cluster_dict(c)
    d["items"] = [dict(item_dict(m.item, c), similarity=m.similarity) for m in visible]
    d["hidden_direct"] = len(members) - len(visible)
    # Reposts of the same text on other sources: kept out of counts, shown so operators can open every original
    copies = clustering.duplicates_of(db, [m.item for m in visible])
    d["copies"] = [{"id": x.id, "duplicate_of_id": x.duplicate_of_id, "platform": x.platform, "url": x.url,
                    "source_name": x.source.name if x.source else None, "published_at": x.published_at.isoformat()}
                   for x in copies if not (x.is_direct and user.role == "viewer")]
    # daily counts for the sparkline
    days: dict[str, int] = {}
    for m in members:
        k = m.item.published_at.date().isoformat()
        days[k] = days.get(k, 0) + 1
    d["timeline"] = [{"date": k, "count": v} for k, v in sorted(days.items())]
    return d


class ClusterUpdate(BaseModel):
    status: Literal["new", "transferred", "in_progress", "resolved", "closed"] | None = None
    department: str | None = None
    title: str | None = Field(None, min_length=3, max_length=280)
    comment: str | None = Field(None, max_length=500)


@router.patch("/{cluster_id}")
def update_cluster(cluster_id: int, body: ClusterUpdate, db: Session = Depends(get_db),
                   user: User = Depends(require_role("operator"))):
    c = db.get(Cluster, cluster_id, options=[joinedload(Cluster.members).joinedload(ClusterItem.item)
                                             .joinedload(Item.enrichment)])
    if c is None:
        raise HTTPException(404, "Проблема не найдена")
    changes = {}
    if body.department and body.department != c.department:
        if not db.scalar(select(Department.id).where(Department.code == body.department)):
            raise HTTPException(400, "Неизвестное подразделение")
        changes["department"] = [c.department, body.department]
        c.department = body.department
    if body.title and body.title != c.title:
        changes["title"] = [c.title, body.title]
        c.title = body.title
    if body.status and body.status != c.status:
        changes["status"] = [c.status, body.status]
        c.status = body.status
        c.status_changed_at = utcnow()
        for m in c.members:   # routing the problem routes all its messages
            if m.item.status not in ("resolved", "closed") or body.status in ("resolved", "closed"):
                set_item_status(m.item, body.status)
    items = [m.item for m in c.members]
    clustering.update_cluster_stats(c, items, copies=clustering.duplicates_of(db, items))
    audit(db, user, "cluster.update", "cluster", c.id, changes=changes, comment=body.comment)
    db.commit()
    return get_cluster(cluster_id, db, user)


@router.post("/recluster")
def recluster(db: Session = Depends(get_db), user: User = Depends(require_role("operator"))):
    stats = clustering.recluster(db)
    audit(db, user, "cluster.recluster", stats=stats)
    db.commit()
    return stats
