import pytest

from app.ai import llm,local_client
from app.config import Settings
from app.reference import DEPARTMENTS


def payload():
    return {'version':'cityalert-e5-routed-v4','predictions':{k:{'label':v,'score':0.99} for k,v in
            [('department','housing'),('sentiment','negative'),('message_type','complaint'),('geo','local')]}}


def test_disabled_default_does_not_call_local_service(monkeypatch):
    assert Settings(_env_file=None).local_model_enabled is False
    monkeypatch.setattr(llm.get_settings(),'local_model_enabled',False)
    monkeypatch.setattr(llm,'get_client',lambda:None)
    monkeypatch.setattr(local_client,'analyse',lambda *a:pytest.fail('Disabled local model called'))
    assert llm.enrich('Павлодар. Нет воды',DEPARTMENTS).model=='rules-v1'


def test_enabled_local_adapter_preserves_review_and_never_calls_external(monkeypatch):
    monkeypatch.setattr(llm.get_settings(),'local_model_enabled',True)
    monkeypatch.setattr(llm,'get_client',lambda:pytest.fail('External API called in local mode'))
    monkeypatch.setattr(local_client,'analyse',lambda text,depts,*a:local_client.convert(payload(),text,depts))
    out=llm.enrich('Павлодар. Нет отопления',DEPARTMENTS)
    assert out.model=='local:cityalert-e5-routed-v4'
    assert out.result.primary_department=='housing'
    assert out.result.department_confidence==0.0
    assert out.result.geo.relevance=='possible'
    assert 'no_heat' in out.result.urgency_markers


def test_local_failure_uses_rules_without_external_api(monkeypatch):
    monkeypatch.setattr(llm.get_settings(),'local_model_enabled',True)
    monkeypatch.setattr(llm,'get_client',lambda:pytest.fail('External API called'))
    def fail(*args):raise RuntimeError('offline')
    monkeypatch.setattr(local_client,'analyse',fail)
    result=llm.enrich('Нет воды',DEPARTMENTS)
    assert result.model=='rules-v1 (local fallback)'
    assert result.result.department_confidence==0 and result.error


def test_model_url_is_loopback_only():
    assert local_client.local_url('http://127.0.0.1:8012/')=='http://127.0.0.1:8012/predict'
    for bad in ['https://example.org','http://example.org','http://127.0.0.1.evil.org',
                'http://user:password@localhost:8012','http://localhost:8012/x','http://localhost:8012?token=x']:
        with pytest.raises(ValueError):local_client.local_url(bad)


def test_invalid_model_prediction_is_rejected():
    data=payload();data['predictions']['department']['label']='unknown-service'
    with pytest.raises(ValueError):local_client.convert(data,'текст',DEPARTMENTS)


def test_archived_model_assets_are_complete_and_match_checksums():
    import hashlib
    import json
    from pathlib import Path
    assets=Path(__file__).parents[1]/'app/local_model_assets'
    checks=json.loads((assets/'SHA256SUMS.json').read_text(encoding='utf-8'))
    for filename,digest in checks.items():
        assert Path(filename).name==filename
        assert hashlib.sha256((assets/filename).read_bytes()).hexdigest()==digest
    manifest=json.loads((assets/'heads.json').read_text(encoding='utf-8'))
    assert manifest['version']=='cityalert-e5-routed-v4'
    for field in ('general_file','contextual_file'):
        expert=json.loads((assets/manifest[field]).read_text(encoding='utf-8'))
        dimension=384+len(expert['features']['idf'])
        for head in expert['heads'].values():
            if not head['constant']:
                assert all(len(coef)==dimension for coef in head['coef'])
