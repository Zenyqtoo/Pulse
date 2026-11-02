"""Safe JSON serialization of local text features; no pickle or model downloads here."""
import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer


def texts_for_features(rows, genre_aware=False):
    output = []
    for row in rows:
        text = row["text"] + ("\nКонтекст: " + row["context"] if row.get("context") else "")
        if genre_aware:
            kind = row.get("kind")
            genre = ("публикация" if kind in ("article","post") else
                     "комментарий" if kind in ("comment","reply","message","review") else "не указан")
            text = f"Жанр: {genre}.\n" + text
        output.append(text)
    return output


def encoder_texts(rows, state):
    return ["query: " + text[:4800] for text in texts_for_features(rows, state.get("input_format")=="genre-v1")]


def fit_lexical(texts):
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=12000,
                                 sublinear_tf=True, dtype=np.float64)
    matrix = vectorizer.fit_transform(texts)
    state = {"vocabulary": {k: int(v) for k, v in vectorizer.vocabulary_.items()}, "idf": vectorizer.idf_.tolist(),
             "ngram_range": [3, 5], "semantic_scale": 2.0, "lexical_scale": 1.0}
    return matrix, state


def transform_lexical(texts, state):
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=tuple(state["ngram_range"]),
                                 vocabulary=state["vocabulary"], sublinear_tf=True, dtype=np.float64)
    vectorizer.idf_ = np.asarray(state["idf"], dtype=float)
    return vectorizer.transform(texts)


def combine_features(embeddings, lexical, state):
    return hstack((csr_matrix(embeddings * state["semantic_scale"]), lexical * state["lexical_scale"]), format="csr")
