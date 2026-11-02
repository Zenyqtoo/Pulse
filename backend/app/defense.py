"""Reproducible editorial selections of existing public evidence, separate from automatic clusters."""
import json
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import joinedload

from app.ai.clustering import update_cluster_stats
from app.audit import audit
from app.models import Cluster, ClusterItem, Item

MANIFEST = Path(__file__).parent / "data" / "defense_cases.json"


def prepare_cases(db):
    result = []
    for spec in json.loads(MANIFEST.read_text(encoding="utf8")):
        items = db.scalars(select(Item).options(joinedload(Item.source), joinedload(Item.enrichment))
                          .where(Item.url.in_(spec["urls"]), Item.is_direct.is_(False),
                                 Item.is_spam.is_(False), Item.duplicate_of_id.is_(None))).unique().all()
        items = [i for i in items if i.source and not i.source.is_synthetic]
        if not items:
            continue
        tag = "curated:" + spec["key"]
        cluster = db.scalar(select(Cluster).where(Cluster.summary_model == tag))
        if cluster is None:
            cluster = Cluster(title=spec["title"], department=spec["department"], summary_model=tag, active=False)
            db.add(cluster)
            db.flush()
        # Inactive means selected dossier, not a claim that a historical issue is currently happening.
        cluster.active = False
        cluster.title, cluster.summary = spec["title"], spec["summary"]
        db.execute(delete(ClusterItem).where(ClusterItem.cluster_id == cluster.id))
        db.add_all(ClusterItem(cluster_id=cluster.id, item_id=i.id, similarity=0) for i in items)
        update_cluster_stats(cluster, items)
        audit(db, None, "defense.prepare", "cluster", cluster.id, selection=spec["key"],
              item_ids=[i.id for i in items], note="Редакторская подборка реальных записей; не автоматический кластер")
        result.append({"id": cluster.id, "key": spec["key"], "items": len(items)})
    db.commit()
    return result
