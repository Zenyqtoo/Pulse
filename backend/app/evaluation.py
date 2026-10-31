"""Accuracy measurement on human-labelled items (acceptance criterion 6).

- Labels are made blind (the labelling UI hides AI predictions).
- Each labelled item gets a fixed dev/test split (25% dev for prompt tuning, 75% test for reporting).
- Test items are excluded from few-shot examples, so the reported numbers are not leaked.
- Metrics are computed on the model's ORIGINAL output (model_* fields), not on operator corrections.
- Results are split by origin: real collected data vs the synthetic demo set.
"""
from collections import Counter

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.ai import llm
from app.models import EvalRun, GoldLabel, Item, Source
from app.reference import DEPT_CODES

SENTS = ["positive", "neutral", "negative"]


def split_for(item_id: int) -> str:
    return "dev" if (item_id * 2654435761) % 100 < 25 else "test"


def _gold_rows(db: Session, split: str, origin: str):
    stmt = (select(GoldLabel, Item).join(Item, Item.id == GoldLabel.item_id).join(Source, Source.id == Item.source_id)
            .options(joinedload(Item.enrichment)))
    if split != "all":
        stmt = stmt.where(GoldLabel.split == split)
    if origin == "real":
        stmt = stmt.where(Source.is_synthetic.is_(False))
    elif origin == "synthetic":
        stmt = stmt.where(Source.is_synthetic.is_(True))
    return db.execute(stmt).unique().all()


def _metrics(gold: list[str], pred: list[str], labels: list[str]) -> dict:
    present = [l for l in labels if l in gold or l in pred]
    rep = classification_report(gold, pred, labels=present, output_dict=True, zero_division=0)
    return {
        "accuracy": round(accuracy_score(gold, pred), 4),
        "macro_f1": round(f1_score(gold, pred, labels=present, average="macro", zero_division=0), 4),
        "labels": present,
        "confusion": confusion_matrix(gold, pred, labels=present).tolist(),
        "per_class": {l: {"precision": round(rep[l]["precision"], 3), "recall": round(rep[l]["recall"], 3),
                          "f1": round(rep[l]["f1-score"], 3), "support": int(rep[l]["support"])} for l in present},
    }


def evaluate(db: Session, split: str = "test", origin: str = "real", mode: str = "stored",
             departments: list[dict] | None = None) -> EvalRun:
    rows = _gold_rows(db, split, origin)
    gd, pd, gs, ps, lenient, langs, models = [], [], [], [], [], [], Counter()
    for g, it in rows:
        if mode == "rerun":
            out = llm.enrich(it.text_masked, departments or [], [])
            pdept, pdepts, psent, model = out.result.primary_department, out.result.departments, out.result.sentiment, out.model
        else:
            e = it.enrichment
            if e is None:
                continue
            pdept = e.model_department or e.primary_department
            pdepts = e.model_departments or e.departments
            psent = e.model_sentiment or e.sentiment
            model = e.model
        models[model] += 1
        gd.append(g.department)
        pd.append(pdept)
        gs.append(g.sentiment)
        ps.append(psent)
        lenient.append(g.department in (pdepts or [pdept]))
        langs.append(it.lang or "other")
    n = len(gd)
    run = EvalRun(split=split, origin=origin, n=n, prompt_version=mode,
                  model=", ".join(f"{m} ×{c}" for m, c in models.most_common()) or "—")
    if n:
        dm = _metrics(gd, pd, DEPT_CODES)
        sm = _metrics(gs, ps, SENTS)
        run.dept_accuracy, run.dept_macro_f1 = dm["accuracy"], dm["macro_f1"]
        run.sentiment_accuracy, run.sentiment_macro_f1 = sm["accuracy"], sm["macro_f1"]
        run.dept_accuracy_lenient = round(sum(lenient) / n, 4)
        by_lang = {}
        for lang in sorted(set(langs)):
            idx = [i for i, l in enumerate(langs) if l == lang]
            by_lang[lang] = {"n": len(idx),
                             "dept_accuracy": round(sum(gd[i] == pd[i] for i in idx) / len(idx), 4),
                             "sentiment_accuracy": round(sum(gs[i] == ps[i] for i in idx) / len(idx), 4)}
        run.details = {"department": dm, "sentiment": sm, "by_lang": by_lang,
                       "targets": {"sentiment": 0.80, "department": 0.75}}
    db.add(run)
    db.commit()
    return run


def run_dict(r: EvalRun) -> dict:
    return {"id": r.id, "created_at": r.created_at.isoformat(), "split": r.split, "origin": r.origin,
            "mode": r.prompt_version, "model": r.model, "n": r.n, "dept_accuracy": r.dept_accuracy,
            "dept_accuracy_lenient": r.dept_accuracy_lenient, "sentiment_accuracy": r.sentiment_accuracy,
            "dept_macro_f1": r.dept_macro_f1, "sentiment_macro_f1": r.sentiment_macro_f1, "details": r.details}
