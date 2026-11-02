"""Train v2 on labelled synthetic curriculum + downweighted weak real train data.

Frozen e5 encoder, char n-gram features, regularized classifiers. No held-out data
used for feature fitting or training. Output is versioned, not enabled in app.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sys

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.ai.local_features import combine_features, encoder_texts, fit_lexical, texts_for_features
from local_curriculum import curriculum
from train_local_model import MODEL, TASKS, fit_heads, model_text, training_rows


def build_training(dataset, genre_aware=False):
    weak, manifest = training_rows(dataset)
    synthetic = curriculum()
    rows = [{**r, "labels": labels, "origin": "real_rules_v1", "sample_weight": 0.12}
            for r, labels in weak] + synthetic
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate training examples")
    assert all(manifest["assignments"][r["id"]]["split"] == "train" for r in rows if r["origin"] == "real_rules_v1")
    if genre_aware:
        for row in rows:
            row["labels"] = dict(row["labels"])
            if row["origin"] == "real_rules_v1":
                row["sample_weight"] = 0.5
                if row.get("kind") in ("article","post") and row["labels"]["message_type"] != "spam":
                    row["labels"]["message_type"] = "info"
                    # An adverse event alone does not make a neutral news report a complaint.
                    if row["labels"]["sentiment"] == "negative" and not re.search(
                        r"ужас|безобраз|кошмар|позор|возмущ|недоволь|разочаров|жалуюсь|наша[рр]|шағымдан",row["text"],re.I):
                        row["labels"]["sentiment"] = "neutral"
            elif int(row["id"][-2:],16) % 2 == 0:
                row["kind"] = "article" if row["labels"]["message_type"] == "info" else "comment"
    return rows, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--revision", default="614241f622f53c4eeff9890bdc4f31cfecc418b3")
    parser.add_argument("--genre-aware",action="store_true",help="Use known record genre and correct weak news labels")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Output must be empty; model version is never overwritten")
    rows, manifest = build_training(args.dataset,args.genre_aware)
    args.output.mkdir(parents=True, exist_ok=True)
    train_text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    (args.output / "training_records.jsonl").write_text(train_text, encoding="utf-8")
    from sentence_transformers import SentenceTransformer
    import torch

    torch.set_num_threads(4)
    print(f"Training v2: {len(rows)} examples; local encoder; held-out labels unused", flush=True)
    encoder = SentenceTransformer(MODEL, revision=args.revision, device="cpu", cache_folder=str(args.cache),
                                  local_files_only=True, trust_remote_code=False)
    input_state = {"input_format":"genre-v1"} if args.genre_aware else {}
    embedded = encoder.encode(encoder_texts(rows,input_state) if args.genre_aware else [model_text(r) for r in rows], normalize_embeddings=True, batch_size=16,
                              show_progress_bar=True)
    lexical, feature_state = fit_lexical(texts_for_features(rows,args.genre_aware))
    feature_state.update(input_state)
    features = combine_features(embedded, lexical, feature_state)
    print(f"Feature matrix {features.shape}; fitting classifier heads", flush=True)
    heads = fit_heads(features, [r["labels"] for r in rows], C=15.0,
                      sample_weight=np.array([r["sample_weight"] for r in rows]))
    payload = {"format": "cityalert-local-heads-v2", "version": "cityalert-e5-genre-v3" if args.genre_aware else "cityalert-e5-curriculum-v2", "encoder": MODEL,
               "encoder_revision": args.revision, "prefix": "query: ", "heads": heads, "features": feature_state}
    (args.output / "heads.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    card = {"version": payload["version"], "created_at": datetime.now(timezone.utc).isoformat(),
            "encoder": MODEL, "encoder_revision": args.revision, "encoder_weights_updated": False,
            "adaptation": "frozen encoder + char n-grams + weighted trained logistic heads (C=15)",
            "training_origins": dict(Counter(r["origin"] for r in rows)),
            "training_sha256": hashlib.sha256(train_text.encode()).hexdigest(),
            "weak_real_weight": 0.5 if args.genre_aware else 0.12, "synthetic_weight": 1.0,
            "weak_media_labels_adjusted": args.genre_aware,
            "label_counts": {task: dict(Counter(r["labels"][task] for r in rows)) for task in TASKS},
            "real_held_out": manifest["split_counts"], "independent_human_accuracy": None,
            "limitations": ["AI-authored templates are not real resident comments or independent gold labels.",
                            "Old 28 diagnostic examples informed development; report them as regressions only.",
                            "Uncalibrated scores; human real-data validation still required.",
                            "Do not automatically enable or replace the deployed analyser from this script."]}
    (args.output / "model_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(card, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
