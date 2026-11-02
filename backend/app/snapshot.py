"""Import the sanitized, offline hackathon dataset into an empty installation."""
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, func, select

from app.models import Cluster, ClusterItem, Enrichment, Item, Source

SNAPSHOT = Path(__file__).parent / "demo" / "public_snapshot.json"


def load_snapshot(db, path=SNAPSHOT):
    """Keep existing users/configuration; refuse to merge with existing messages."""
    if db.scalar(select(func.count()).select_from(Item)):
        raise ValueError("Снимок загружается только в базу без сообщений. Используйте новую установку.")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != "cityalert-public-v1":
        raise ValueError("Неизвестный формат снимка")

    def values(model, row, excluded=()):
        out = {}
        for col in model.__table__.columns:
            if col.name not in row or col.name in excluded:
                continue
            value = row[col.name]
            if isinstance(col.type, DateTime) and value is not None:
                value = datetime.fromisoformat(value)
            out[col.name] = value
        return out

    sources, items, clusters = {}, {}, {}
    try:
        for row in data["sources"]:
            obj = Source(**values(Source, row, ("id", "config", "enabled", "last_error")))
            obj.config, obj.enabled = {}, False
            db.add(obj)
            db.flush()
            sources[row["id"]] = obj.id
        for row in data["items"]:
            obj = Item(**values(Item, row, ("id", "source_id", "duplicate_of_id", "reply_ref")))
            obj.source_id = sources[row["source_id"]]
            obj.reply_ref = None
            if obj.is_direct:
                raise ValueError("Личные сообщения недопустимы в публичном снимке")
            db.add(obj)
            db.flush()
            items[row["id"]] = obj
        for row in data["items"]:
            if row.get("duplicate_of_id") in items:
                items[row["id"]].duplicate_of_id = items[row["duplicate_of_id"]].id
        for row in data["enrichments"]:
            obj = Enrichment(**values(Enrichment, row, ("item_id", "reviewed_by")))
            obj.item_id, obj.reviewed_by = items[row["item_id"]].id, None
            db.add(obj)
        for row in data["clusters"]:
            obj = Cluster(**values(Cluster, row, ("id",)))
            db.add(obj)
            db.flush()
            clusters[row["id"]] = obj.id
        for row in data["members"]:
            db.add(ClusterItem(cluster_id=clusters[row["cluster_id"]],
                               item_id=items[row["item_id"]].id, similarity=row["similarity"]))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"items": len(items), "sources": len(sources), "clusters": len(clusters),
            "note": "Исторические даты сохранены; расширьте период фильтра. Сборщики снимка выключены."}
