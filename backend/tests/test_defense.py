from types import SimpleNamespace

from app.api.defense import cases
from app.defense import prepare_cases
from app.models import Item, Source


def test_defense_requires_login(client):
    assert client.get('/api/defense/cases').status_code == 401


def test_curated_cases_count_real_public_records_and_scope(db):
    src = Source(type='city_web', name='Public test', platform='news', config={}, is_synthetic=False)
    db.add(src)
    db.flush()
    from app.models import utcnow
    url = 'https://gorodpavlodar.kz/News_117838_2.html'
    for key, direct, spam, kind in [('article', False, False, 'article'), ('comment', False, False, 'comment'),
                                    ('private', True, False, 'message'), ('spam', False, True, 'article')]:
        db.add(Item(source_id=src.id, external_id=key, url=url, text='Fixture', text_masked='Fixture',
                    content_hash=key, published_at=utcnow(), kind=kind, is_direct=direct, is_spam=spam))
    db.commit()
    try:
        prepared = prepare_cases(db)
        assert len(prepared) == 1 and prepared[0]['items'] == 2
        prepare_cases(db)  # repeat does not duplicate the dossier or its members
        visible = cases(db, SimpleNamespace(department_code=None))
        assert len(visible) == 1
        assert visible[0]['coverage'] == {'residents': 1, 'media': 1, 'sources': 1}
        assert visible[0]['primary_sources'] == [{'url': url, 'label': 'Public test'}]
        assert cases(db, SimpleNamespace(department_code='education')) == []
        src.is_synthetic = True
        db.flush()
        assert cases(db, SimpleNamespace(department_code=None)) == []
    finally:
        # This fixture is shared with the broader suite; remove the selected dossier and our records.
        from sqlalchemy import delete
        from app.models import Cluster, ClusterItem
        ids = [r['id'] for r in prepared]
        db.execute(delete(ClusterItem).where(ClusterItem.cluster_id.in_(ids)))
        db.execute(delete(Cluster).where(Cluster.id.in_(ids)))
        db.execute(delete(Item).where(Item.source_id == src.id))
        db.delete(src)
        db.commit()
