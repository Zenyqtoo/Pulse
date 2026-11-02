import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("prepare_training", Path(__file__).parents[1] / "scripts/prepare_training.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def item(id, text, **kwargs):
    return dict(id=id, external_id=str(id), source_id=1, text_masked=text, published_at="2026-11-01",
                **kwargs)


def test_blind_real_only_grouped_transitive_and_duplicates():
    snapshot = {"sources": [dict(id=1, type="news", name="Public", is_synthetic=False),
                             dict(id=2, type="demo", name="Demo", is_synthetic=True)],
                "items": [item(1, "Первое сообщение", url="https://example.org/article"),
                          item(2, "Другое сообщение", parent_url="https://example.org/article?cpage=2"),
                          item(3, "Другое сообщение", url="https://another.org/post"),
                          item(4, "Сильно сокращённый текст", duplicate_of_id=3),
                          item(5, "private", is_direct=True),
                          {**item(6, "synthetic"), "source_id": 2}],
                "enrichments": [{"item_id": 1, "primary_department": "housing", "sentiment": "negative"}]}
    records, manifest = module.prepare(snapshot)
    assert len(records) == 4
    assert len({a["group"] for a in manifest["assignments"].values()}) == 1
    assert len({a["split"] for a in manifest["assignments"].values()}) == 1
    assert all(not any(r["labels"].values()) and r["label_origin"] == "unlabeled" for r in records)
    assert all("primary_department" not in r and "_original_id" not in r for r in records)
    assert module.prepare(snapshot)[1]["assignments"] == manifest["assignments"]


def test_reject_incomplete_forged_or_duplicate_labels():
    records = [{"id": "a"}]
    manifest = {"assignments": {"a": {"split": "test"}}}
    label = {"id": "a", "reviewer": "reviewer-1", "label_origin": "human",
             "labels": {k: next(iter(v)) for k, v in module.FIELDS.items()}}
    assert module.validate(records, [label], manifest) == {"test": 1}
    for bad in ([{**label, "label_origin": "rules-v1"}], [{**label, "reviewer": ""}],
                [{**label, "labels": {}}], [label, label], [{**label, "id": "unknown"}]):
        with pytest.raises(ValueError):
            module.validate(records, bad, manifest)


def test_weak_labels_never_cover_dev_or_test():
    records = [{"id": key, "source": "Public", "text": "Павлодар: нет отопления", "context": "", "kind": "comment"}
               for key in ("a", "b", "c")]
    manifest = {"assignments": {"a": {"split": "train"}, "b": {"split": "dev"}, "c": {"split": "test"}}}
    snapshot = {"sources": [{"name": "Public", "geo_scope": "city"}]}
    labels = module.weak_train_labels(records, manifest, snapshot)
    assert len(labels) == 1 and labels[0]["id"] == "a"
    assert labels[0]["label_origin"] == "rules-v1" and labels[0]["reviewer"] is None
    with pytest.raises(ValueError):
        module.validate(records, labels, manifest)
