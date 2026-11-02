"""Compare saved versions on disclosed diagnostics and AI-reviewed real dev data."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.ai.local_features import combine_features, encoder_texts, texts_for_features, transform_lexical
from app.ai.local_routing import route_predictions
from train_local_model import model_text, predict_heads, TASKS


def metrics(rows, version):
    result = {}
    for task in TASKS:
        eligible = [r for r in rows if r.get("expected", {}).get(task) is not None]
        correct = sum(r[version][task]["label"] == r["expected"][task] for r in eligible)
        result[task] = {"correct": correct, "n": len(eligible)}
    result["all_fields"] = {"correct": sum(all(r[version][t]["label"] == e for t,e in r["expected"].items() if e is not None)
                                                   for r in rows if r.get("expected")),
                            "n": sum(bool(r.get("expected")) for r in rows)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--gallery", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refuse to overwrite evaluation: use a new report file")
    old, new = [json.loads((p / "heads.json").read_text(encoding="utf-8")) for p in (args.old, args.new)]
    routed = new["format"]=="cityalert-local-experts-v4"
    if routed:
        general = json.loads((args.new/new['general_file']).read_text(encoding='utf-8'))
        contextual = json.loads((args.new/new['contextual_file']).read_text(encoding='utf-8'))
        manifest = new
        new = contextual
    if (old["encoder"],old["encoder_revision"]) != (new["encoder"],new["encoder_revision"]):
        raise ValueError("Shared features require the same encoder revision")
    review = json.loads(args.review.read_text(encoding="utf-8"))
    gallery = json.loads(args.gallery.read_text(encoding="utf-8"))
    groups = {"old_diagnostics": [{**r,"origin":"old_development"} for r in gallery[:28]],
              "fresh_diagnostics": review["fresh"], "real_dev_ai_reviewed": review["real_dev"]}
    rows = [dict(row,group=group) for group,examples in groups.items() for row in examples]
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(4)
    encoder = SentenceTransformer(new["encoder"], revision=new["encoder_revision"], cache_folder=str(args.cache),
                                  device="cpu", local_files_only=True, trust_remote_code=False)
    embedded = encoder.encode([model_text(r) for r in rows], normalize_embeddings=True, batch_size=16,
                              show_progress_bar=True)
    genre_aware = new["features"].get("input_format")=="genre-v1"
    new_embedded = encoder.encode(encoder_texts(rows,new["features"]),normalize_embeddings=True,batch_size=16,
                                 show_progress_bar=True) if genre_aware else embedded
    features = combine_features(new_embedded, transform_lexical(texts_for_features(rows,genre_aware),new["features"]),new["features"])
    if routed:
        general_features = combine_features(embedded,transform_lexical(texts_for_features(rows),general['features']),general['features'])
    for i,row in enumerate(rows):
        row["old"] = predict_heads(embedded[i:i+1],old["heads"])
        contextual_prediction = predict_heads(features[i:i+1],new["heads"])
        row["new"] = route_predictions(row.get('kind'),predict_heads(general_features[i:i+1],general['heads']),contextual_prediction) if routed else contextual_prediction
        for version in ("old","new"):
            row[version+"_errors"] = [t for t,e in row["expected"].items() if e is not None and row[version][t]["label"] != e]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "old_version":"cityalert-e5-weak-v1",
              "new_version":manifest['version'] if routed else new["version"], "reference_origin":"AI-authored diagnostics and AI-reviewed real dev; NOT human gold",
              "warning":"Old examples informed development; new diagnostics are synthetic; real dev is mostly media. No acceptance accuracy claim.",
              "metrics":{group:{version:metrics([r for r in rows if r['group']==group],version) for version in ('old','new')}
                         for group in groups}, "examples":rows}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report["metrics"],ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
