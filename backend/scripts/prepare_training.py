"""Prepare blind annotation data from the sanitized snapshot, without database access.

Run from backend: python scripts/prepare_training.py --output ../../work/pulse-study/training-v1
No existing model predictions or synthetic examples enter the real evaluation pool.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.reference import DEPT_NAMES

FIELDS = {
    "geo": {"local": "Павлодар", "not_local": "Другой город / только область", "possible": "Место неясно"},
    "department": DEPT_NAMES | {"not_applicable": "Не относится к работе служб"},
    "sentiment": {"negative": "Негативная", "neutral": "Нейтральная", "positive": "Положительная"},
    "message_type": {"complaint": "Жалоба", "question": "Вопрос", "proposal": "Предложение",
                     "gratitude": "Благодарность", "info": "Информация", "spam": "Спам / реклама"},
    "voice": {"resident": "Комментарий / обращение пользователя", "media": "Редакция / СМИ",
              "official": "Официальная организация", "unknown": "Автор неясен"},
    "language": {"ru": "Русский", "kk": "Казахский", "mixed": "Смешанный", "other": "Другой"},
}


def normalized(text):
    return re.sub(r"\W+", " ", (text or "").casefold().replace("ё", "е")).strip()


def url_key(value):
    if not value:
        return None
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def prepare(snapshot):
    sources = {s["id"]: s for s in snapshot["sources"]}
    # Whitelist fields: never leak geo, spam or sentiment predictions to annotators.
    records = []
    for item in snapshot["items"]:
        source = sources[item["source_id"]]
        if source["is_synthetic"] or item.get("is_direct"):
            continue
        text = item.get("text_masked") or ""
        if not text.strip():
            continue
        stable = f"{source['type']}:{source['name']}:{item['external_id']}"
        records.append({"id": hashlib.sha256(stable.encode()).hexdigest()[:20],
                        "text": text, "context": item.get("context_text") or "",
                        "url": item.get("url"), "parent_url": item.get("parent_url"),
                        "source": source["name"], "source_type": source["type"],
                        "published_at": item["published_at"], "kind": item.get("kind"),
                        "labels": {k: "" for k in FIELDS}, "reviewer": "", "notes": "",
                        "label_origin": "unlabeled", "_original_id": item["id"],
                        "_duplicate_of": item.get("duplicate_of_id")})
    records.sort(key=lambda r: r["id"])
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        a, b = find(i), find(j)
        parent[max(a, b)] = min(a, b)

    positions = {r["_original_id"]: i for i, r in enumerate(records)}
    for i, row in enumerate(records):
        if row["_duplicate_of"] in positions:
            join(i, positions[row["_duplicate_of"]])
    seen = {}
    shingles = []
    for i, row in enumerate(records):
        text = normalized(row["text"])
        words = text.split()
        shingles.append({tuple(words[k:k + 4]) for k in range(max(0, len(words) - 3))})
        keys = [("text", text)]
        for value in (row["url"], row["parent_url"]):
            if key := url_key(value):
                keys.append(("article", key))
        for key in keys:
            if key in seen:
                join(i, seen[key])
            else:
                seen[key] = i
    # Cross-source near-reposts: conservative word-shingle similarity.
    # All transitive matches and comments on the same article stay in one split.
    for i, a in enumerate(shingles):
        if len(a) < 8:
            continue
        for j in range(i):
            b = shingles[j]
            if len(b) < 8 or min(len(a), len(b)) / max(len(a), len(b)) < 0.8:
                continue
            if len(a & b) / len(a | b) >= 0.8:
                join(i, j)
    groups = {}
    for i, record in enumerate(records):
        groups.setdefault(find(i), []).append(record)
    assignments = {}
    for members in groups.values():
        group_id = min(r["id"] for r in members)
        bucket = int(hashlib.sha256(("cityalert-v1:" + group_id).encode()).hexdigest()[:8], 16) % 100
        split = "train" if bucket < 70 else "dev" if bucket < 85 else "test"
        for row in members:
            assignments[row["id"]] = {"group": group_id, "split": split}
    manifest = {"format": "cityalert-training-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_exported_at": snapshot.get("exported_at"), "records": len(records),
                "groups": len(groups), "largest_group": max(map(len, groups.values()), default=0),
                "split_counts": dict(Counter(a["split"] for a in assignments.values())),
                "source_counts": dict(Counter(r["source"] for r in records)),
                "kind_counts": dict(Counter(r["kind"] for r in records)),
                "assignments": assignments,
                "warnings": ["No human labels yet; no accuracy claim.",
                             "Grouping mitigates obvious leakage, not every paraphrase or event overlap.",
                             "Current sources are mostly media; expand resident comments and Kazakh examples.",
                             "Do not tune or train on test labels, including via prompts or corrections."]}
    for row in records:
        row.pop("_original_id")
        row.pop("_duplicate_of")
    return records, manifest


def validate(records, labels, manifest):
    known = {r["id"] for r in records}
    seen, counts = set(), Counter()
    for row in labels:
        if row["id"] not in known or row["id"] in seen:
            raise ValueError("Unknown or duplicate annotation id")
        seen.add(row["id"])
        if row.get("label_origin") != "human" or not row.get("reviewer", "").strip():
            raise ValueError("Human reviewer and explicit label provenance required")
        for name, choices in FIELDS.items():
            if row.get("labels", {}).get(name) not in choices:
                raise ValueError(f"Incomplete/invalid {name} for {row['id']}")
        counts[manifest["assignments"][row["id"]]["split"]] += 1
    return dict(counts)


def weak_train_labels(records, manifest, snapshot):
    """Only the training partition receives heuristic labels; never a human test set."""
    from app.ai import rules
    from app.ai.lang import detect_language
    from app.geo import classify_rules
    from app.reference import DEPARTMENTS

    sources = {s["name"]: s for s in snapshot["sources"]}
    output = []
    for row in records:
        if manifest["assignments"][row["id"]]["split"] != "train":
            continue
        result = rules.analyse(row["text"], DEPARTMENTS)
        geo = classify_rules(row["text"], sources[row["source"]].get("geo_scope", "unknown"), row["context"])
        output.append({"id": row["id"], "label_origin": "rules-v1", "reviewer": None,
                       "labels": {"geo": geo.status, "department": result.primary_department,
                                  "sentiment": result.sentiment,
                                  "message_type": "spam" if result.is_spam else result.message_type,
                                  "voice": "resident" if row["kind"] in ("comment", "reply", "message", "review") else "media",
                                  "language": detect_language(row["text"])},
                       "note": "Automatic training labels, not human ground truth or evaluation data."})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=BACKEND / "app/demo/public_snapshot.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate", type=Path, help="Validate exported annotation JSON; does not import into DB")
    parser.add_argument("--weak-train", action="store_true", help="Add explicitly heuristic labels for train only")
    args = parser.parse_args()
    if args.validate:
        records = [json.loads(s) for s in (args.output / "blind.jsonl").read_text(encoding="utf-8").splitlines()]
        manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
        labels = json.loads(args.validate.read_text(encoding="utf-8"))
        print(json.dumps({"reviewed_by_split": validate(records, labels, manifest)}, ensure_ascii=False))
        return
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Output directory must be empty; existing annotation work is never overwritten")
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    records, manifest = prepare(snapshot)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "blind.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    template = (Path(__file__).parent / "annotation_template.html").read_text(encoding="utf-8")
    payload = json.dumps({"records": records, "fields": FIELDS}, ensure_ascii=False).replace("</", "<\\/")
    (args.output / "annotate.html").write_text(template.replace("__DATA__", payload), encoding="utf-8")
    if args.weak_train:
        labels = weak_train_labels(records, manifest, snapshot)
        (args.output / "weak_train_labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "assignments"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
