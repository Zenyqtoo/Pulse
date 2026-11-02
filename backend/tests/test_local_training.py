import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location("train_local_model", Path(__file__).parents[1] / "scripts/train_local_model.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_serialized_binary_multiclass_and_constant_heads():
    features = np.array([[-2, 0], [-1, 0], [1, 0], [2, 0], [0, 2], [0, 3]], dtype=float)
    labels = [{"department": "housing" if x < 0 else "roads" if x > 0 else "health",
               "sentiment": "negative" if x < 0 else "neutral", "message_type": "info", "geo": "local"}
              for x, y in features]
    heads = json.loads(json.dumps(module.fit_heads(features, labels)))
    result = module.predict_heads(np.array([[-3, 0]]), heads)
    assert result["department"]["label"] == "housing"
    assert result["sentiment"]["label"] == "negative"
    assert result["message_type"]["constant"]
    assert all(0 <= p["score"] <= 1 for p in result.values())


def test_training_rejects_any_held_out_label(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"assignments": {"a": {"split": "test"}}}))
    (tmp_path / "blind.jsonl").write_text(json.dumps({"id": "a"}) + "\n")
    (tmp_path / "weak_train_labels.json").write_text(json.dumps([{"id": "a", "label_origin": "rules-v1", "labels": {}}]))
    with pytest.raises(ValueError, match="held-out"):
        module.training_rows(tmp_path)
