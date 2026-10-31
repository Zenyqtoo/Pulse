"""Background jobs: hourly collection (3.1.4), near-real-time Direct polling, priority refresh,
and Direct retention (3.7.4). Runs inside the API process: no Redis/Celery needed for the MVP."""
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, select

from app import pipeline
from app.ai import clustering
from app.config import get_settings
from app.db import SessionLocal
from app.models import Item, Source

log = logging.getLogger("pulse.scheduler")
_scheduler: BackgroundScheduler | None = None


def _with_db(fn):
    def run():
        db = SessionLocal()
        try:
            fn(db)
        except Exception:
            log.exception("job %s failed", fn.__name__)
        finally:
            db.close()
    run.__name__ = fn.__name__
    return run


def collect_job(db):
    log.info("scheduled collection: %s", pipeline.collect_all(db, "schedule", only_due=True))


def bot_job(db):
    if not get_settings().telegram_bot_token:
        return
    new = 0
    for src in db.scalars(select(Source).where(Source.type == "telegram_bot", Source.enabled.is_(True))).all():
        run = pipeline.run_source(db, src, "schedule")
        new += run.new_items
    if new:
        if pipeline.process_pending(db).get("processed"):
            pipeline.after_processing(db)


def priority_job(db):
    clustering.refresh_priorities(db)


def retention_job(db):
    cutoff = datetime.now(timezone.utc) - timedelta(days=get_settings().direct_retention_days)
    n = db.execute(delete(Item).where(Item.is_direct.is_(True), Item.published_at < cutoff)).rowcount
    db.commit()
    if n:
        log.info("retention: deleted %s Direct items older than %s", n, cutoff.date())


def token_refresh_job(db):
    """Meta long-lived tokens last ~60 days; refresh them when they have < 15 days left."""
    from app.api.connect import refresh_token
    from app.integrations import tokens

    for platform in ("instagram", "threads"):
        cred = tokens.load(db, platform)
        if cred and cred.origin == "oauth" and cred.expires_at and \
                cred.expires_at - datetime.now(timezone.utc) < timedelta(days=15):
            try:
                refresh_token(db, platform)
                log.info("%s token refreshed", platform)
            except Exception as e:
                log.warning("%s token refresh failed: %s", platform, e)


def start() -> None:
    global _scheduler
    s = get_settings()
    if not s.scheduler_enabled or _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(_with_db(collect_job), "interval", minutes=s.collect_interval_minutes, id="collect",
                       next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30), max_instances=1, coalesce=True)
    _scheduler.add_job(_with_db(bot_job), "interval", seconds=s.bot_poll_seconds, id="bot", max_instances=1, coalesce=True)
    _scheduler.add_job(_with_db(priority_job), "interval", minutes=30, id="priority", max_instances=1, coalesce=True)
    _scheduler.add_job(_with_db(retention_job), "interval", hours=24, id="retention", max_instances=1, coalesce=True)
    _scheduler.add_job(_with_db(token_refresh_job), "interval", hours=12, id="tokens", max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("scheduler started")


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
