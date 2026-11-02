"""Selected, explicitly dated real evidence briefs; all counters come from visible DB rows."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Cluster, ClusterItem, Item, User
from app.security import get_current_user
from app.serializers import iso, voice

router = APIRouter(prefix="/api/defense", tags=["defense"])
CASES = Path(__file__).resolve().parents[1] / "data" / "defense_cases.json"


@router.get("/cases")
def cases(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    manifest = json.loads(CASES.read_text(encoding="utf8"))
    out = []
    for spec in manifest:
        cluster = db.scalar(select(Cluster).where(Cluster.summary_model == "curated:" + spec["key"]))
        if cluster is None or (user.department_code and cluster.department != user.department_code):
            continue
        items = db.scalars(select(Item).join(ClusterItem, ClusterItem.item_id == Item.id)
                          .options(joinedload(Item.source))
                          .where(ClusterItem.cluster_id == cluster.id)).unique().all()
        # Curated defense cases are public and real for every role. Never leak Direct or synthetic data.
        items = [i for i in items if i.source and not i.source.is_synthetic and not i.is_direct
                 and not i.is_spam and i.duplicate_of_id is None]
        if not items:
            continue
        residents = sum(voice(i) == "resident" for i in items)
        links = {}
        for item in items:
            if item.url and urlsplit(item.url).scheme in ("http", "https"):
                links[item.url] = {"url": item.url, "label": item.source.name}
        out.append({"id": cluster.id, "title": cluster.title, "summary": cluster.summary,
                    "why_demo": spec["why_demo"], "period_note": spec["period_note"],
                    "evidence_note": spec["evidence_note"],
                    "coverage": {"residents": residents, "media": len(items) - residents,
                                 "sources": len({i.source_id for i in items})},
                    "primary_sources": list(links.values()), "updated_at": iso(cluster.updated_at)})
    return out
