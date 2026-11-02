from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

from sqlalchemy import select

from app.decision import build_decision
from app.models import Cluster, User
from app.security import create_token, hash_password


def message(id, date, author=None, direct=False, kind="post", source_type="demo"):
    return N(id=id, published_at=date, author_hash=author, source_id=1, kind=kind,
             source=N(name="Тестовый источник", is_synthetic=source_type == "demo", type=source_type),
             text_masked="Просим вернуть отопление. Телефон [ТЕЛЕФОН].", is_direct=direct, url=None,
             enrichment=N(problem_type="Нет отопления", object=None, urgency_markers=["children"], departments=["housing"]))


def test_decision_metrics_use_real_denominator_and_local_hours():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    c = N(id=1, title="Нет отопления", department="housing", district=None)
    rows = [message(1, now - timedelta(hours=1), "a"), message(2, now - timedelta(hours=2), "a"),
            message(3, now - timedelta(hours=25))]
    d = build_decision(c, rows, now)
    assert d["metrics"] == {"messages": 3, "known_accounts": 1, "messages_without_author": 1,
                             "sources": 1, "current_24h": 2, "previous_24h": 1, "growth_pct": 100,
                             "growth_abs": 1, "small_base": True, "synthetic_messages": 3,
                             "direct_messages": 0, "hidden_direct": 0, "resident_messages": 3, "media_posts": 0}
    assert d["daily"] == [{"date": "2026-10-31", "count": 1}, {"date": "2026-11-01", "count": 2}]
    assert d["related_departments"] == []   # the responsible department is not repeated as "related"
    assert any("осторожно" in g for g in d["checks"])
    assert {p["hour"] for p in d["peaks"]} == {15, 16}
    assert d["synthetic"] and d["affected"] == ["дети"]
    assert d["topics"][0]["item_ids"] == [1, 2, 3]
    assert all(q["item_id"] in [1, 2, 3] for q in d["demands"])


def test_decision_missing_baseline_and_empty_are_not_fabricated():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    c = N(id=1, title="Проблема", department="housing", district=None)
    d = build_decision(c, [message(1, now)], now)
    assert d["metrics"]["growth_pct"] is None
    assert not build_decision(c, [], now)["available"]


def test_decision_and_patch_enforce_department_before_commit(client, db):
    user = User(login="decision_roads", full_name="Оператор", role="operator", department_code="roads",
                password_hash=hash_password("test-password"))
    c = Cluster(department="housing", title="Чужая проблема", summary="", status="new")
    db.add_all([user, c])
    db.commit()
    headers = {"Authorization": "Bearer " + create_token(user)}
    assert client.get(f"/api/clusters/{c.id}/decision", headers=headers).status_code == 403
    assert client.patch(f"/api/clusters/{c.id}", headers=headers, json={"title": "Недопустимое изменение"}).status_code == 403
    db.expire_all()
    assert db.get(Cluster, c.id).title == "Чужая проблема"


def test_decision_viewer_gets_only_public_evidence(client, viewer, operator, db):
    c = db.scalar(select(Cluster).where(Cluster.active.is_(True)))
    op = client.get(f"/api/clusters/{c.id}/decision", headers=operator)
    public = client.get(f"/api/clusters/{c.id}/decision", headers=viewer)
    assert op.status_code == public.status_code == 200
    d = public.json()
    assert not any(i["is_direct"] for i in d["evidence"])
    assert d["metrics"]["messages"] == len(d["evidence"])
    assert all(i["id"] in {x["id"] for x in op.json()["evidence"]} for i in d["evidence"])


def test_decision_voices_prefer_public_messages():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    c = N(id=1, title="Проблема", department="housing", district="Центр")
    rows = [message(1, now, direct=True), message(2, now - timedelta(hours=1)), message(3, now - timedelta(hours=2))]
    d = build_decision(c, rows, now)
    assert [v["id"] for v in d["voices"]] == [2, 3]
    assert d["metrics"]["direct_messages"] == 1


def test_quality_labeling_is_scoped_to_department(client, db):
    user = User(login="quality_roads", full_name="Оператор", role="operator", department_code="roads",
                password_hash=hash_password("test-password"))
    db.add(user)
    db.commit()
    headers = {"Authorization": "Bearer " + create_token(user)}
    r = client.get("/api/quality/labeling", params={"origin": "all", "limit": 100}, headers=headers)
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    from app.models import Enrichment
    if ids:
        depts = set(db.scalars(select(Enrichment.primary_department).where(Enrichment.item_id.in_(ids))).all())
        assert depts == {"roads"}
    foreign = db.scalar(select(Enrichment.item_id).where(Enrichment.primary_department != "roads"))
    r = client.put(f"/api/quality/gold/{foreign}", headers=headers, json={"department": "roads", "sentiment": "neutral"})
    assert r.status_code == 403


def test_decision_never_quotes_news_as_residents():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    c = N(id=1, title="Отопление", department="housing", district=None)
    rows = [message(1, now, source_type="news", kind="article"), message(2, now, source_type="telegram_web")]
    d = build_decision(c, rows, now)
    assert d["metrics"]["resident_messages"] == 0 and d["metrics"]["media_posts"] == 2
    assert d["voices"] == [] and d["demands"] == []
    assert "жителей" in d["checks"][0] and not d["synthetic"]
    rows.append(message(3, now, source_type="news", kind="comment"))
    d = build_decision(c, rows, now)
    assert [v["id"] for v in d["voices"]] == [3] and d["evidence"][0]["voice"] in ("media", "resident")


def test_voice_filter_separates_residents_from_media(client, operator):
    total = client.get("/api/items", params={"days": 3650}, headers=operator).json()["total"]
    residents = client.get("/api/items", params={"days": 3650, "voice": "resident"}, headers=operator).json()["total"]
    media = client.get("/api/items", params={"days": 3650, "voice": "media"}, headers=operator).json()["total"]
    assert residents + media == total and media == 0   # the test set is the synthetic resident demo only
    assert client.get("/api/items", params={"voice": "robots"}, headers=operator).status_code == 422
