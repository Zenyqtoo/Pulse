"""Synthetic demo dataset (clearly labelled as such in the UI and excluded from 'real' accuracy).

Used for development, automated tests and as a fallback demo when live sources are unreachable.
Message dates are relative to 'now' so the dashboards show recent activity.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.collectors.base import Collector, RawItem

DATA = Path(__file__).resolve().parent.parent / "demo" / "demo_messages.json"


def load_demo() -> list[dict]:
    return json.loads(DATA.read_text(encoding="utf-8"))


class DemoCollector(Collector):
    type = "demo"
    title = "Демо-набор (синтетические сообщения)"
    description = "Синтетические сообщения для разработки и запасного сценария демо. Не являются реальными данными."
    config_fields = []

    def fetch(self, since: datetime | None) -> list[RawItem]:
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        out = []
        for row in load_demo():
            out.append(RawItem(
                external_id=row["id"], text=row["text"],
                published_at=now - timedelta(hours=row["hours_ago"]),
                url=None, author_id=row.get("author"), platform=row.get("platform", "demo"),
                reactions=row.get("reactions", 0), replies=row.get("replies", 0), views=row.get("views", 0),
                is_direct=row.get("direct", False),
            ))
        return out
