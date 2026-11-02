"""Group similar items into problems (clusters), keep cluster identity stable across runs,
compute priority, and generate titles/summaries."""
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.ai import embeddings, llm, priority
from app.models import Cluster, ClusterItem, Enrichment, Item

log = logging.getLogger("pulse.clustering")
WINDOW_DAYS = 45


def _signature(item: Item) -> str:
    """Normalised problem type and district dominate; raw text adds nuance.
    Weights were chosen with scripts/cluster_quality.py on the labelled demo groups."""
    e = item.enrichment
    parts = []
    if e and e.problem_type:
        parts += [e.problem_type] * 5
    if e and e.district:
        parts += [e.district] * 3
    if e and e.object:
        parts.append(e.object)
    parts.append(item.text_masked[:200])
    return " | ".join(parts)


def _groups(items: list[Item], threshold: float) -> list[list[int]]:
    if len(items) == 1:
        return [[0]], embeddings.embed([_signature(items[0])])
    vecs = embeddings.embed([_signature(i) for i in items])
    model = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                    distance_threshold=1 - threshold)
    labels = model.fit_predict(vecs)
    groups: dict[int, list[int]] = {}
    for idx, lab in enumerate(labels):
        groups.setdefault(int(lab), []).append(idx)
    return _merge_same_problem(items, list(groups.values())), vecs


def headline(text: str, limit: int = 80) -> str:
    """First sentence of a message or article without leading emoji, cut at a word boundary."""
    t = re.sub(r"^[^\wА-Яа-яЁё«\"(]+", "", (text or "").strip())
    first, _, rest = t.partition("\n")
    if rest.strip() and first.isupper() and len(first.split()) <= 3:   # channel rubric such as "ПОДРОБНОСТИ"
        t = re.sub(r"^[^\wА-Яа-яЁё«\"(]+", "", rest.strip())
    t = re.split(r"(?<=[.!?])\s|\n", t, maxsplit=1)[0].strip().rstrip(".")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",;:—–-") + "…"
    return t or "Проблема без названия"


def _key(item: Item) -> tuple[str, str] | None:
    e = item.enrichment
    if not e or not e.problem_type:
        return None
    return e.problem_type.strip().lower(), (e.district or "").strip().lower()


def _merge_same_problem(items: list[Item], groups: list[list[int]]) -> list[list[int]]:
    """Explainable rule on top of similarity: the same normalised problem type in the same
    district is one problem, even when residents describe it in very different words."""
    merged: dict[tuple, list[int]] = {}
    rest: list[list[int]] = []
    for g in groups:
        keys = Counter(_key(items[i]) for i in g if _key(items[i]))
        if not keys:
            rest.append(g)
            continue
        k, n = keys.most_common(1)[0]
        if n * 2 < len(g):   # no dominant key: keep the similarity group as is
            rest.append(g)
            continue
        merged.setdefault(k, []).extend(g)
    return list(merged.values()) + rest


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def duplicates_of(db: Session, items: list[Item]) -> list[Item]:
    ids = [i.id for i in items]
    if not ids:
        return []
    return db.scalars(select(Item).where(Item.duplicate_of_id.in_(ids))).all()


def update_cluster_stats(c: Cluster, items: list[Item], now: datetime | None = None,
                         copies: list[Item] | None = None) -> None:
    now = now or _now()
    times = [_aware(i.published_at) for i in items]
    c.item_count = len(items)
    c.count_24h = sum(1 for t in times if t >= now - timedelta(hours=24))
    c.count_prev_24h = sum(1 for t in times if now - timedelta(hours=48) <= t < now - timedelta(hours=24))
    c.growth_rate = round(priority.growth(c.count_24h, c.count_prev_24h), 2)
    negs = [i for i in items if i.enrichment and i.enrichment.sentiment == "negative"]
    c.neg_share = round(len(negs) / len(items), 2) if items else 0
    c.reach = int(sum(i.reactions + i.replies + i.views / 100 for i in items))
    markers: set[str] = set()
    for i in items:
        if i.enrichment:
            markers |= set(i.enrichment.urgency_markers or [])
    c.has_urgent = bool(markers)
    c.first_seen = min(times) if times else None
    c.last_seen = max(times) if times else None
    resolved = c.status in ("resolved", "closed")
    days = 0.0 if resolved or not c.first_seen else (now - c.first_seen).total_seconds() / 86400
    level, score, factors = priority.compute(priority.PriorityInput(
        neg_share=c.neg_share, n=c.item_count, count_24h=c.count_24h, count_prev_24h=c.count_prev_24h,
        engagement=c.reach, urgent_markers=markers, days_unresolved=days))
    c.priority, c.priority_score, c.priority_factors = level, score, factors
    platforms = Counter(i.platform for i in items)
    sources = {i.source_id for i in items}
    for d in (copies or []):          # the same text reposted elsewhere still counts as attention there
        platforms[d.platform] += 0
        sources.add(d.source_id)
    c.platforms = sorted(platforms, key=lambda k: -platforms[k])
    c.source_count = len(sources)
    districts = Counter(i.enrichment.district for i in items if i.enrichment and i.enrichment.district)
    c.district = districts.most_common(1)[0][0] if districts else None
    c.updated_at = now


def recluster(db: Session, summarise: bool = True, threshold: float | None = None) -> dict:
    """Re-cluster recent analysed items per department. Returns run stats."""
    threshold = threshold or embeddings.default_threshold()
    since = _now() - timedelta(days=WINDOW_DAYS)
    items = db.scalars(
        select(Item).options(joinedload(Item.enrichment), joinedload(Item.source))
        .where(Item.process_state == "done", Item.is_spam.is_(False), Item.duplicate_of_id.is_(None),
               Item.geo_status == "local", Item.published_at >= since)
    ).unique().all()
    # Real and synthetic messages never share a problem: a demo complaint must not inflate a real one
    by_dept: dict[tuple[str, bool], list[Item]] = {}
    for it in items:
        if it.enrichment and it.enrichment.message_type != "gratitude":
            by_dept.setdefault((it.enrichment.primary_department, bool(it.source and it.source.is_synthetic)), []).append(it)

    existing = db.scalars(select(Cluster).options(joinedload(Cluster.members)).where(Cluster.active.is_(True))).unique().all()
    existing_sets = {c.id: {m.item_id for m in c.members} for c in existing}
    existing_by_id = {c.id: c for c in existing}
    used: set[int] = set()
    stats = {"items": len(items), "clusters": 0, "new": 0, "kept": 0, "retired": 0, "summaries": 0}

    for (dept, _synthetic), dept_items in by_dept.items():
        groups, vecs = _groups(dept_items, threshold)
        for g in groups:
            members = [dept_items[i] for i in g]
            urgent = any(m.enrichment.urgency_markers for m in members)
            if len(members) < 2 and not urgent:
                continue
            ids = {m.id for m in members}
            centroid = vecs[g].mean(axis=0)
            norm = np.linalg.norm(centroid) or 1.0
            sims = {dept_items[i].id: float(vecs[i] @ centroid / norm) for i in g}

            best, best_j = None, 0.0
            for cid, cset in existing_sets.items():
                if cid in used or existing_by_id[cid].department != dept:
                    continue
                j = len(ids & cset) / len(ids | cset)
                if j > best_j:
                    best, best_j = cid, j
            if best is not None and best_j >= 0.3:
                c = existing_by_id[best]
                used.add(best)
                changed = len(ids ^ existing_sets[best]) / max(1, len(ids)) > 0.3
                c.members.clear()
                db.flush()
                stats["kept"] += 1
            else:
                c = Cluster(department=dept, title="", status="new", active=True)
                db.add(c)
                db.flush()
                changed = True
                stats["new"] += 1
            for m in members:
                c.members.append(ClusterItem(item_id=m.id, similarity=round(sims[m.id], 3)))
            update_cluster_stats(c, members, copies=duplicates_of(db, members))
            types = Counter(m.enrichment.problem_type for m in members if m.enrichment.problem_type)
            hint = types.most_common(1)[0][0] if types else headline(min(members, key=lambda m: len(m.text_masked)).text_masked)
            if c.district and c.district.lower() not in hint.lower():
                hint = f"{hint} — {c.district}"
            # Extractive titles are free to recompute, so they always follow the current members
            if summarise and (changed or not c.summary or c.summary_model == "extractive"):
                ordered = sorted(members, key=lambda m: -sims[m.id])
                c.title, c.summary, c.summary_model = llm.summarise_cluster([m.text_masked for m in ordered], hint)
                stats["summaries"] += 1
            elif not c.title:
                c.title = hint
            # items inherit the problem's status unless they were handled individually
            for m in members:
                if m.status == "new" and c.status != "new":
                    m.status = c.status
            stats["clusters"] += 1

    for cid, c in existing_by_id.items():
        if cid not in used:
            c.active = False
            stats["retired"] += 1
    db.commit()
    log.info("recluster: %s", stats)
    return stats


def refresh_priorities(db: Session) -> None:
    """Recompute time-dependent stats (growth, duration) without re-clustering."""
    clusters = db.scalars(select(Cluster).options(joinedload(Cluster.members).joinedload(ClusterItem.item)
                                                  .joinedload(Item.enrichment))
                          .where(Cluster.active.is_(True))).unique().all()
    for c in clusters:
        items = [m.item for m in c.members]
        update_cluster_stats(c, items, copies=duplicates_of(db, items))
    db.commit()
