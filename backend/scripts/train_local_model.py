"""Train local classification heads on a frozen open multilingual encoder.

This is adaptation by linear probing, NOT fine-tuning the encoder weights.
Weak train labels are explicitly marked. Dev/test are not used or scored.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

MODEL = "intfloat/multilingual-e5-small"
TASKS = ("department", "sentiment", "message_type", "geo")


def model_text(row):
    return "query: " + row["text"][:3500] + ("\nКонтекст: " + row["context"][:1200] if row.get("context") else "")


def training_rows(dataset):
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    records = {r["id"]: r for r in map(json.loads, (dataset / "blind.jsonl").read_text(encoding="utf-8").splitlines())}
    labels = json.loads((dataset / "weak_train_labels.json").read_text(encoding="utf-8"))
    seen = set()
    rows = []
    for label in labels:
        key = label["id"]
        if key in seen or key not in records or manifest["assignments"][key]["split"] != "train":
            raise ValueError("Invalid/duplicate id or held-out data in training labels")
        if label["label_origin"] != "rules-v1":
            raise ValueError("This bootstrap script expects explicit weak labels")
        seen.add(key)
        rows.append((records[key], label["labels"]))
    if len(rows) < 10:
        raise ValueError("Too few training examples")
    return rows, manifest


def fit_heads(features, labels, C=1.0, sample_weight=None):
    heads = {}
    for task in TASKS:
        target = [row[task] for row in labels]
        if len(set(target)) == 1:
            heads[task] = {"classes": [target[0]], "constant": True}
            continue
        classifier = LogisticRegression(C=C, max_iter=1000, class_weight="balanced", random_state=42)
        classifier.fit(features, target, sample_weight=sample_weight)
        heads[task] = {"classes": classifier.classes_.tolist(), "coef": classifier.coef_.tolist(),
                       "intercept": classifier.intercept_.tolist(), "constant": False}
    return heads


def predict_heads(features, heads):
    result = {}
    for task, head in heads.items():
        if head["constant"]:
            result[task] = {"label": head["classes"][0], "score": 1.0, "constant": True}
            continue
        logits = features @ np.asarray(head["coef"]).T + np.asarray(head["intercept"])
        if len(head["classes"]) == 2:
            logits = np.concatenate([np.zeros_like(logits), logits], axis=-1)
        logits = logits - np.max(logits, axis=-1, keepdims=True)
        probabilities = np.exp(logits) / np.exp(logits).sum(axis=-1, keepdims=True)
        idx = int(np.argmax(probabilities))
        result[task] = {"label": head["classes"][idx], "score": float(probabilities.reshape(-1)[idx]),
                        "constant": False}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Output must be empty; do not overwrite a deployed model")
    rows, manifest = training_rows(args.dataset)
    from sentence_transformers import SentenceTransformer
    import torch

    torch.set_num_threads(min(4, torch.get_num_threads()))
    print(f"Loading {MODEL}; training heads on {len(rows)} weakly labelled texts", flush=True)
    encoder = SentenceTransformer(MODEL, device="cpu", cache_folder=str(args.cache), trust_remote_code=False)
    features = encoder.encode([model_text(r) for r, _ in rows], normalize_embeddings=True,
                              batch_size=8, show_progress_bar=True)
    heads = fit_heads(features, [labels for _, labels in rows])
    args.output.mkdir(parents=True, exist_ok=True)
    revision = getattr(encoder[0].auto_model.config, "_commit_hash", None)
    cached_ref = args.cache / ("models--" + MODEL.replace("/", "--")) / "refs/main"
    if not revision and cached_ref.exists():
        revision = cached_ref.read_text(encoding="utf-8").strip()
    payload = {"format": "cityalert-local-heads-v1", "encoder": MODEL, "encoder_revision": revision,
               "prefix": "query: ", "heads": heads}
    (args.output / "heads.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    card = {"version": "cityalert-e5-weak-v1", "created_at": datetime.now(timezone.utc).isoformat(),
            "encoder": MODEL, "encoder_revision": revision, "adaptation": "frozen encoder + trained logistic heads",
            "encoder_weights_updated": False, "training_labels": "rules-v1 (weak, not manually verified)",
            "training_examples": len(rows), "train_ids_sha256": hashlib.sha256("\n".join(sorted(r['id'] for r,_ in rows)).encode()).hexdigest(),
            "label_counts": {task: dict(Counter(labels[task] for _, labels in rows)) for task in TASKS},
            "held_out_examples": manifest["split_counts"], "independent_accuracy": None,
            "limitations": ["Bootstrap model may reproduce and amplify rule errors.",
                            "No independent quality or probability calibration claim.",
                            "Kazakh and resident-comment coverage inadequate.",
                            "No test/dev labels used; deployment not enabled by this script."]}
    (args.output / "model_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(card, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
