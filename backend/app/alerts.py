"""Telegram alerts for critical problems (spec 3.8.5). Sent once per cluster."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.telegram_bot import send_message
from app.config import get_settings
from app.models import Cluster, utcnow
from app.reference import DEPT_NAMES, URGENCY_MARKERS

log = logging.getLogger("pulse.alerts")


def critical_clusters(db: Session) -> list[Cluster]:
    return db.scalars(select(Cluster).where(Cluster.active.is_(True), Cluster.priority == "high",
                                            Cluster.alerted_at.is_(None),
                                            Cluster.status.in_(["new", "transferred"]))).all()


def format_alert(c: Cluster) -> str:
    markers = (c.priority_factors or {}).get("terms", {}).get("urgency", {}).get("value", "")
    readable = ", ".join(URGENCY_MARKERS.get(m.strip(), m) for m in markers.split(",") if m.strip() and m != "нет")
    return (f"⚠️ Высокий приоритет: {c.title}\n"
            f"Подразделение: {DEPT_NAMES.get(c.department, c.department)}\n"
            f"Обращений: {c.item_count} (за 24 ч: {c.count_24h}), балл {c.priority_score}"
            + (f"\nСрочность: {readable}" if readable else "")
            + f"\nПроблема #{c.id} в панели «Пульс города».")


def send_alerts(db: Session) -> int:
    s = get_settings()
    if not (s.telegram_bot_token and s.telegram_alert_chat_id):
        return 0
    sent = 0
    for c in critical_clusters(db):
        try:
            send_message(s.telegram_alert_chat_id, format_alert(c))
            c.alerted_at = utcnow()
            sent += 1
        except Exception as e:
            log.warning("alert for cluster %s failed: %s", c.id, e)
    db.commit()
    return sent
