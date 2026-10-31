"""Response shapes. List endpoints never include original text: only the masked version."""
from app.models import Cluster, Enrichment, Item
from app.reference import DEPT_NAMES


def enrichment_dict(e: Enrichment | None) -> dict | None:
    if e is None:
        return None
    return {
        "departments": e.departments, "primary_department": e.primary_department,
        "dept_confidence": e.dept_confidence, "sentiment": e.sentiment, "sentiment_score": e.sentiment_score,
        "sentiment_confidence": e.sentiment_confidence, "message_type": e.message_type,
        "district": e.district, "address": e.address, "object": e.object, "problem_type": e.problem_type,
        "urgency_markers": e.urgency_markers or [], "is_urgent": e.is_urgent, "rationale": e.rationale,
        "model": e.model, "prompt_version": e.prompt_version, "latency_ms": e.latency_ms,
        "needs_review": e.needs_review, "reviewed": e.reviewed,
        "reviewed_at": e.reviewed_at.isoformat() if e.reviewed_at else None,
        "model_department": e.model_department, "model_sentiment": e.model_sentiment,
        "corrected": bool(e.reviewed and (e.model_department != e.primary_department or e.model_sentiment != e.sentiment)),
    }


def item_dict(it: Item, cluster: Cluster | None = None, full: bool = False) -> dict:
    d = {
        "id": it.id, "source_id": it.source_id, "source_name": it.source.name if it.source else None,
        "source_type": it.source.type if it.source else None,
        "is_synthetic": bool(it.source and it.source.is_synthetic),
        "url": it.url, "text": it.text_masked, "lang": it.lang,
        "published_at": it.published_at.isoformat(), "collected_at": it.collected_at.isoformat() if it.collected_at else None,
        "author": (it.author_hash or "")[:8] or None,
        "reactions": it.reactions, "replies": it.replies, "views": it.views,
        "is_direct": it.is_direct, "is_spam": it.is_spam, "spam_reason": it.spam_reason,
        "duplicate_of_id": it.duplicate_of_id, "status": it.status,
        "process_state": it.process_state, "pii_found": it.pii_found or [],
        "enrichment": enrichment_dict(it.enrichment),
        "cluster": {"id": cluster.id, "title": cluster.title, "priority": cluster.priority} if cluster else None,
        "platform": it.platform, "kind": it.kind, "parent_url": it.parent_url,
        "geo_status": it.geo_status, "geo_reason": it.geo_reason, "geo_reviewed": it.geo_reviewed,
    }
    if full:
        d["process_error"] = it.process_error
        d["can_reply"] = bool(it.is_direct and it.reply_ref and it.reply_ref.get("kind") == "telegram")
        d["geo_evidence"] = it.geo_evidence or {}
        d["geo_score"] = it.geo_score
        d["parent_external_id"] = it.parent_external_id
        d["context_text"] = it.context_text
        d["geo_llm"] = it.enrichment.geo_relevance if it.enrichment else None
        d["place_mentioned"] = it.enrichment.place_mentioned if it.enrichment else None
    return d


def cluster_dict(c: Cluster) -> dict:
    return {
        "id": c.id, "title": c.title, "summary": c.summary, "summary_model": c.summary_model,
        "department": c.department, "department_name": DEPT_NAMES.get(c.department, c.department),
        "district": c.district, "item_count": c.item_count, "count_24h": c.count_24h,
        "count_prev_24h": c.count_prev_24h, "growth_rate": c.growth_rate, "neg_share": c.neg_share,
        "reach": c.reach, "has_urgent": c.has_urgent, "priority": c.priority, "priority_score": c.priority_score,
        "priority_factors": c.priority_factors, "status": c.status,
        "status_changed_at": c.status_changed_at.isoformat() if c.status_changed_at else None,
        "first_seen": c.first_seen.isoformat() if c.first_seen else None,
        "last_seen": c.last_seen.isoformat() if c.last_seen else None,
        "active": c.active, "is_hot": c.count_24h >= 3 and c.growth_rate >= 1.5,
        "platforms": c.platforms or [], "source_count": c.source_count,
        "multi_platform": len([p for p in (c.platforms or []) if p not in ("demo", "upload")]) > 1,
    }
