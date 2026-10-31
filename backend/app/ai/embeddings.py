"""Text vectors for clustering and semantic search.

Backend "st": local multilingual sentence-transformers model (if installed and downloaded).
Backend "tfidf": character n-gram TF-IDF, works offline for Russian and Kazakh with no model download.
"auto" picks "st" when available, otherwise "tfidf". The backend in use is shown on the Quality page.
"""
import logging
from functools import lru_cache

import numpy as np

from app.config import get_settings

log = logging.getLogger("pulse.embeddings")


@lru_cache
def _st_model():
    s = get_settings()
    if s.embedding_backend not in ("auto", "st"):
        return None
    try:
        from sentence_transformers import SentenceTransformer  # optional dependency

        return SentenceTransformer(s.embedding_model)
    except Exception as e:  # not installed or model not downloadable
        if s.embedding_backend == "st":
            log.error("sentence-transformers unavailable: %s", e)
        return None


def backend_name() -> str:
    return f"st:{get_settings().embedding_model}" if _st_model() is not None else "tfidf-char-3-5"


def default_threshold() -> float:
    return get_settings().cluster_threshold if _st_model() is not None else 0.35


def embed(texts: list[str]) -> np.ndarray:
    """L2-normalised vectors; rows comparable by dot product."""
    if not texts:
        return np.zeros((0, 1))
    model = _st_model()
    if model is not None:
        vecs = model.encode([f"query: {t}" for t in texts], normalize_embeddings=True, batch_size=32)
        return np.asarray(vecs, dtype=np.float32)
    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True,
                          lowercase=True, max_features=60000)
    m = vec.fit_transform([t.replace("ё", "е") for t in texts])
    dense = m.toarray().astype(np.float32)
    norms = np.linalg.norm(dense, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return dense / norms
