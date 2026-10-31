"""Measure clustering on the synthetic demo set, whose message ids encode the intended problem group.
purity: share of items in a cluster that belong to its majority group (higher = no mixing).
coverage: share of each multi-message group captured by its single largest cluster (higher = less fragmentation).
Usage: python scripts/cluster_quality.py [threshold ...]"""
import sys
from collections import Counter

from sqlalchemy import delete, select, update
from sqlalchemy.orm import joinedload

from app.ai import clustering
from app.db import SessionLocal
from app.models import Cluster, ClusterItem, Item, Source


def group(ext: str) -> str:
    return ext.split("-")[1] if ext.startswith("demo-") else ext


def measure(db, threshold):
    db.execute(delete(ClusterItem))
    db.execute(delete(Cluster))
    db.commit()
    clustering.recluster(db, summarise=False, threshold=threshold)
    demo = db.scalar(select(Source.id).where(Source.type == "demo"))
    cl = db.scalars(select(Cluster).options(joinedload(Cluster.members).joinedload(ClusterItem.item))).unique().all()
    total, pure = 0, 0
    best_by_group: Counter = Counter()
    for c in cl:
        gs = Counter(group(m.item.external_id) for m in c.members if m.item.source_id == demo)
        if not gs:
            continue
        g, n = gs.most_common(1)[0]
        total += sum(gs.values())
        pure += n
        best_by_group[g] = max(best_by_group[g], n)
    sizes = Counter(group(i.external_id) for i in db.scalars(select(Item).where(
        Item.source_id == demo, Item.duplicate_of_id.is_(None), Item.is_spam.is_(False))).all())
    big = {g: n for g, n in sizes.items() if n >= 3}
    coverage = sum(best_by_group[g] for g in big) / sum(big.values())
    print(f"threshold {threshold:.2f}: clusters={len(cl)} purity={pure / max(1, total):.2f} coverage={coverage:.2f}")


if __name__ == "__main__":
    db = SessionLocal()
    for t in [float(x) for x in sys.argv[1:]] or [0.3, 0.35, 0.4, 0.42, 0.45, 0.5, 0.55]:
        measure(db, t)
