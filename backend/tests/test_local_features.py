import importlib.util
from pathlib import Path
import sys

import numpy as np
from scipy.sparse import csr_matrix

from app.ai.local_features import combine_features, encoder_texts, fit_lexical, texts_for_features, transform_lexical

SCRIPTS = Path(__file__).parents[1]/"scripts"
sys.path.insert(0,str(SCRIPTS))
from local_curriculum import curriculum
from train_local_model import fit_heads, predict_heads


def test_json_features_roundtrip_and_sparse_head_predictions():
    import json
    texts = ["Павлодар: отопление", "Павлодар: дороги", "Павлодарда жылу жоқ", "Павлодарда жол жөнделді"]
    lexical,state = fit_lexical(texts)
    state = json.loads(json.dumps(state))
    rebuilt = transform_lexical(texts,state)
    np.testing.assert_allclose(rebuilt.toarray(),lexical.toarray(),atol=1e-12)
    combined = combine_features(np.array([[-2,0],[2,0],[-1,0],[1,0]]), rebuilt,state)
    labels = [{"department": d,"sentiment":"neutral","message_type":"info","geo":"local"}
              for d in ["housing","roads","housing","roads"]]
    heads = json.loads(json.dumps(fit_heads(combined,labels,C=15,sample_weight=np.ones(4))))
    assert predict_heads(combined[0:1],heads)["department"]["label"] == "housing"
    assert predict_heads(combined[1:2],heads)["department"]["label"] == "roads"


def test_curriculum_provenance_and_coverage():
    rows = curriculum()
    assert len(rows)>1000 and len({r['id'] for r in rows})==len(rows)
    assert all(r['origin']=='ai_authored_synthetic' for r in rows)
    assert {r['language'] for r in rows}=={'ru','kk'}
    for language in ('ru','kk'):
        subset = [r for r in rows if r['language']==language]
        assert len({r['labels']['department'] for r in subset})==11
        assert {r['labels']['message_type'] for r in subset}=={'complaint','question','proposal','gratitude','info'}


def test_known_genre_comes_from_metadata_not_expected_answers():
    rows = [{"text":"Плановый ремонт","kind":"article","expected":{"message_type":"complaint"}},
            {"text":"Плановый ремонт","kind":"comment"}, {"text":"Плановый ремонт"}]
    result = encoder_texts(rows,{"input_format":"genre-v1"})
    assert 'Жанр: публикация' in result[0]
    assert 'Жанр: комментарий' in result[1]
    assert 'Жанр: не указан' in result[2]
    assert all('complaint' not in r for r in result)


def test_local_input_validation_limits_and_types():
    from serve_local_model import validate_input
    import pytest
    assert validate_input({"text":"Павлодар"})=={"text":"Павлодар","context":"","kind":""}
    for invalid in ({"text":""},{"text":"a"*6001},{"text":"a","context":3},
                    {"text":"a","kind":"system"},[],{"text":"a","context":"a"*2001}):
        with pytest.raises(ValueError):
            validate_input(invalid)


def test_expert_routing_uses_observed_genre_only():
    from app.ai.local_routing import route_predictions
    general={k:{'label':'general'} for k in ('department','sentiment','message_type','geo')}
    contextual={k:{'label':'contextual'} for k in general}
    for kind in ('article','post'):
        result=route_predictions(kind,general,contextual)
        assert result['department']==general['department']
        assert result['sentiment']==contextual['sentiment']
    for kind in ('comment','reply',None,''):
        result=route_predictions(kind,general,contextual)
        assert result['sentiment']==general['sentiment']
        assert result['geo']==contextual['geo']
    assert all(value['label']=='general' for value in general.values())
