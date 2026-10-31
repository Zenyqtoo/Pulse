"""Database models. Spec section 7 entities + pipeline bookkeeping."""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


STATUSES = ["new", "transferred", "in_progress", "resolved", "closed"]
SENTIMENTS = ["positive", "neutral", "negative"]
MESSAGE_TYPES = ["complaint", "question", "proposal", "gratitude", "info"]
ROLES = ["admin", "operator", "viewer"]
PRIORITIES = ["high", "medium", "low"]


class Department(Base):
    __tablename__ = "department"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    name_kk: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Source(Base):
    __tablename__ = "source"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # telegram_web, telethon, rss, telegram_bot, upload, demo
    name: Mapped[str] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    schedule_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # telegram | instagram | threads | news | direct | upload | demo
    platform: Mapped[str] = mapped_column(String(20), default="other", index=True)
    url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    # Geographic prior for the geo classifier: city (about Pavlodar city), region (Pavlodar region),
    # national (all Kazakhstan), unknown
    geo_scope: Mapped[str] = mapped_column(String(20), default="unknown")
    recommended_key: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


GEO_STATUSES = ["local", "possible", "not_local"]


class Item(Base):
    __tablename__ = "item"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_item_source_ext"),
        Index("ix_item_published", "published_at"),
        Index("ix_item_hash", "content_hash"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(1000))
    text: Mapped[str] = mapped_column(Text)  # original; restricted for Direct
    text_masked: Mapped[str] = mapped_column(Text, default="")
    pii_found: Mapped[list] = mapped_column(JSON, default=list)  # kinds only, never values
    lang: Mapped[str | None] = mapped_column(String(10))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    author_hash: Mapped[str | None] = mapped_column(String(64))
    reactions: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    is_direct: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("item.id", ondelete="SET NULL"))
    is_spam: Mapped[bool] = mapped_column(Boolean, default=False)
    spam_reason: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transferred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    process_state: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|done|error
    process_error: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON)
    # Where a reply can be sent (Direct only). Server-side only, never returned by the API.
    reply_ref: Mapped[dict | None] = mapped_column(JSON)
    # Platform-neutral metadata so the same pipeline handles every source
    platform: Mapped[str] = mapped_column(String(20), default="other", index=True)
    kind: Mapped[str] = mapped_column(String(20), default="post")  # post|comment|reply|message|article|review
    parent_external_id: Mapped[str | None] = mapped_column(String(200))
    parent_url: Mapped[str | None] = mapped_column(String(1000))
    context_text: Mapped[str | None] = mapped_column(Text)  # masked text of the post a comment belongs to
    # Geographic relevance to the monitored city (Pavlodar): local | possible | not_local
    geo_status: Mapped[str] = mapped_column(String(12), default="possible", index=True)
    geo_score: Mapped[float] = mapped_column(Float, default=0.0)
    geo_reason: Mapped[str | None] = mapped_column(Text)
    geo_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    geo_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[Source] = relationship()
    enrichment: Mapped["Enrichment | None"] = relationship(back_populates="item", uselist=False, cascade="all, delete-orphan")


class Enrichment(Base):
    __tablename__ = "enrichment"
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), primary_key=True)
    departments: Mapped[list] = mapped_column(JSON, default=list)
    primary_department: Mapped[str] = mapped_column(String(40), index=True)
    dept_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment: Mapped[str] = mapped_column(String(10), index=True)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    message_type: Mapped[str] = mapped_column(String(20), default="info")
    district: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(300))
    object: Mapped[str | None] = mapped_column(String(300))
    problem_type: Mapped[str | None] = mapped_column(String(300))
    urgency_markers: Mapped[list] = mapped_column(JSON, default=list)
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text, default="")
    # The model's own answer, kept unchanged when an operator corrects the fields above,
    # so accuracy is always measured on AI output, never on human corrections.
    model_department: Mapped[str | None] = mapped_column(String(40))
    model_departments: Mapped[list] = mapped_column(JSON, default=list)
    model_sentiment: Mapped[str | None] = mapped_column(String(10))
    model_message_type: Mapped[str | None] = mapped_column(String(20))
    geo_relevance: Mapped[str | None] = mapped_column(String(12))   # the model's own geo judgement
    place_mentioned: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[Item] = relationship(back_populates="enrichment")


class Correction(Base):
    __tablename__ = "correction"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str | None] = mapped_column(String(200))
    new_value: Mapped[str] = mapped_column(String(200))
    comment: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Cluster(Base):
    __tablename__ = "cluster"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_model: Mapped[str | None] = mapped_column(String(80))
    department: Mapped[str] = mapped_column(String(40), index=True)
    district: Mapped[str | None] = mapped_column(String(200))
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    count_24h: Mapped[int] = mapped_column(Integer, default=0)
    count_prev_24h: Mapped[int] = mapped_column(Integer, default=0)
    growth_rate: Mapped[float] = mapped_column(Float, default=0.0)
    neg_share: Mapped[float] = mapped_column(Float, default=0.0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    has_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[str] = mapped_column(String(10), default="low", index=True)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    priority_factors: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platforms: Mapped[list] = mapped_column(JSON, default=list)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list["ClusterItem"]] = relationship(back_populates="cluster", cascade="all, delete-orphan")


class ClusterItem(Base):
    __tablename__ = "cluster_item"
    cluster_id: Mapped[int] = mapped_column(ForeignKey("cluster.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), primary_key=True, index=True)
    similarity: Mapped[float] = mapped_column(Float, default=0.0)

    cluster: Mapped[Cluster] = relationship(back_populates="members")
    item: Mapped[Item] = relationship()


class GoldLabel(Base):
    """Human labels for the accuracy evaluation (criterion 6)."""
    __tablename__ = "gold_label"
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id", ondelete="CASCADE"), primary_key=True)
    department: Mapped[str] = mapped_column(String(40))
    sentiment: Mapped[str] = mapped_column(String(10))
    split: Mapped[str] = mapped_column(String(10), default="test")  # dev | test
    labeled_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    labeled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvalRun(Base):
    __tablename__ = "eval_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    split: Mapped[str] = mapped_column(String(10))
    origin: Mapped[str] = mapped_column(String(20))  # real | synthetic | all
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    n: Mapped[int] = mapped_column(Integer)
    dept_accuracy: Mapped[float | None] = mapped_column(Float)
    dept_accuracy_lenient: Mapped[float | None] = mapped_column(Float)
    sentiment_accuracy: Mapped[float | None] = mapped_column(Float)
    dept_macro_f1: Mapped[float | None] = mapped_column(Float)
    sentiment_macro_f1: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class User(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(80), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    department_code: Mapped[str | None] = mapped_column(String(40))  # scopes view to one department
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CollectionRun(Base):
    __tablename__ = "collection_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")  # schedule | manual | upload | webhook
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | error
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new_items: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    spam: Mapped[int] = mapped_column(Integer, default=0)
    not_local: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class AppState(Base):
    """Small key-value store (e.g. Telegram bot update offset)."""
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
