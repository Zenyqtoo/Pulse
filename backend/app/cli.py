"""Command line: python -m app.cli <command>

  seed               departments, users, default sources
  load-demo          add the synthetic demo set (clearly labelled) and analyse it
  load-snapshot      import the bundled masked public dataset into an empty installation
  prepare-defense    prepare editorial demonstration cases from existing public records
  collect            run all enabled collectors now
  process            analyse pending items, then re-cluster
  recluster          rebuild problems and priorities
  evaluate           accuracy on gold labels  [--split test|dev|all] [--origin real|synthetic|all] [--rerun]
  label-demo         import gold labels shipped with the synthetic demo set (for pipeline testing only)
  telethon-login     one-time Telegram login for the comments collector
  geo-reclassify     re-run Pavlodar geo classification (after editing the gazetteer or source scopes)
  remask             apply the current masking rules to already stored masked texts (only adds masks)
"""
import argparse
import json
import sys

from sqlalchemy import select

from app import pipeline
from app.ai import clustering
from app.collectors.demo import load_demo
from app.config import get_settings
from app.db import SessionLocal
from app.evaluation import evaluate, split_for
from app.models import GoldLabel, Item, Source
from app.seed import seed


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.cli")
    p.add_argument("command")
    p.add_argument("--split", default="test")
    p.add_argument("--origin", default="real")
    p.add_argument("--rerun", action="store_true")
    a = p.parse_args(argv)
    db = SessionLocal()
    try:
        if a.command == "seed":
            seed(db)
            print("ok")
        elif a.command == "load-snapshot":
            from app.snapshot import load_snapshot

            seed(db)
            print(json.dumps(load_snapshot(db), ensure_ascii=False))
        elif a.command == "prepare-defense":
            from app.defense import prepare_cases

            print(json.dumps(prepare_cases(db), ensure_ascii=False))
        elif a.command == "load-demo":
            seed(db)
            src = db.scalar(select(Source).where(Source.type == "demo"))
            if src is None:
                src = Source(type="demo", name="Демо-набор (синтетический)", config={}, is_synthetic=True,
                             enabled=True, schedule_minutes=1440, platform="demo", geo_scope="city",
                             description="Синтетические сообщения, составленные командой. Не реальные данные.")
                db.add(src)
                db.commit()
            run = pipeline.run_source(db, src, "manual")
            print(f"demo: fetched {run.fetched}, new {run.new_items}, duplicates {run.duplicates}, spam {run.spam}")
            print("process:", pipeline.process_pending(db, limit=5000))
            print("clusters:", pipeline.after_processing(db))
        elif a.command == "collect":
            print(json.dumps(pipeline.collect_all(db, "manual", only_due=False), ensure_ascii=False, default=str))
        elif a.command == "process":
            print(pipeline.process_pending(db, limit=5000))
            print(pipeline.after_processing(db))
        elif a.command == "geo-reclassify":
            from app.pipeline import apply_geo

            n = 0
            for it in db.scalars(select(Item).where(Item.geo_reviewed.is_(False))).all():
                apply_geo(it, it.enrichment.geo_relevance if it.enrichment else None)
                n += 1
            db.commit()
            print(f"reclassified {n} items; run `process` to analyse newly local items")
        elif a.command == "remask":
            from app.ai.masking import mask_pii

            n = 0
            for it in db.scalars(select(Item)).all():
                masked, pii = mask_pii(it.text_masked, strict_address=it.is_direct)
                if masked != it.text_masked:
                    it.text_masked, it.pii_found = masked, sorted(set(it.pii_found or []) | set(pii))
                    n += 1
            db.commit()
            print(f"remasked {n} items")
        elif a.command == "recluster":
            print(clustering.recluster(db))
        elif a.command == "label-demo":
            src = db.scalar(select(Source).where(Source.type == "demo"))
            gold = {r["id"]: r for r in load_demo() if r.get("gold_department")}
            n = 0
            for it in db.scalars(select(Item).where(Item.source_id == src.id)).all():
                g = gold.get(it.external_id)
                if g and not db.get(GoldLabel, it.id):
                    db.add(GoldLabel(item_id=it.id, department=g["gold_department"], sentiment=g["gold_sentiment"],
                                     split=split_for(it.id)))
                    n += 1
            db.commit()
            print(f"labelled {n} synthetic items (origin=synthetic; not a measure of real-data accuracy)")
        elif a.command == "evaluate":
            r = evaluate(db, a.split, a.origin, "rerun" if a.rerun else "stored", pipeline._departments(db))
            print(json.dumps({"n": r.n, "model": r.model, "dept_accuracy": r.dept_accuracy,
                              "dept_accuracy_lenient": r.dept_accuracy_lenient,
                              "sentiment_accuracy": r.sentiment_accuracy}, ensure_ascii=False))
        elif a.command == "telethon-login":
            s = get_settings()
            if not s.telegram_api_id or not s.telegram_api_hash:
                sys.exit("Задайте TELEGRAM_API_ID и TELEGRAM_API_HASH в .env (my.telegram.org)")
            from pathlib import Path

            from telethon.sync import TelegramClient

            Path(s.telegram_session_path).parent.mkdir(parents=True, exist_ok=True)

            with TelegramClient(s.telegram_session_path, s.telegram_api_id, s.telegram_api_hash) as c:
                print("Вход выполнен как", c.get_me().first_name)
        else:
            print(__doc__)
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
