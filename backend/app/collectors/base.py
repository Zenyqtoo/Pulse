"""Connector interface: a new source is one class with fetch() — no changes to the core (spec section 4)."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawItem:
    external_id: str
    text: str
    published_at: datetime
    url: str | None = None
    author_id: str | None = None   # hashed before storage, never stored raw
    platform: str = "web"
    reactions: int = 0
    replies: int = 0
    views: int = 0
    is_direct: bool = False
    kind: str = "post"                      # post | comment | reply | message | article | review
    parent_external_id: str | None = None   # thread relationship (comment → post, reply → comment)
    parent_url: str | None = None
    context_text: str | None = None         # text of the parent post, used as context for geo + AI
    extra: dict = field(default_factory=dict)


class CollectorError(Exception):
    """Raised with a human-readable message shown on the Sources page."""


class Collector:
    type: str = "base"
    title: str = "Base"
    description: str = ""
    config_fields: list[dict] = []   # rendered as a form in the admin UI

    def __init__(self, config: dict):
        self.config = config or {}
        self.warnings: list[str] = []   # partial failures, shown in the collection log

    def fetch(self, since: datetime | None) -> list[RawItem]:
        raise NotImplementedError
