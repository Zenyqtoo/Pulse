"""End-to-end API tests on the analysed synthetic demo set: the critical demo path."""
import io

from openpyxl import load_workbook
from sqlalchemy import select

from app.models import AuditLog, Correction, Item


def test_login_and_roles(client, viewer):
    assert client.get("/api/items").status_code == 401
    assert client.post("/api/auth/login", json={"login": "admin", "password": "wrong"}).status_code == 401
    assert client.get("/api/auth/me", headers=viewer).json()["role"] == "viewer"
    assert client.get("/api/users", headers=viewer).status_code == 403


def test_feed_filters(client, operator):
    r = client.get("/api/items", params={"department": "housing", "sentiment": "negative"}, headers=operator).json()
    assert r["total"] > 5
    assert all(i["enrichment"]["primary_department"] == "housing" for i in r["items"])
    q = client.get("/api/items", params={"q": "Торайгырова"}, headers=operator).json()
    assert q["total"] >= 5
    hi = client.get("/api/items", params={"priority": "high"}, headers=operator).json()
    assert hi["total"] > 0 and all(i["cluster"]["priority"] == "high" for i in hi["items"])


def test_direct_is_restricted(client, viewer, operator, db):
    # viewers never see Direct messages in the feed
    v = client.get("/api/items", params={"is_direct": "true"}, headers=viewer).json()
    assert v["total"] == 0
    o = client.get("/api/items", params={"is_direct": "true"}, headers=operator).json()
    assert o["total"] >= 5
    d = o["items"][0]
    assert "[" in d["text"] or d["pii_found"] == []        # masked in lists
    assert client.get(f"/api/items/{d['id']}", headers=viewer).status_code == 403
    assert client.get(f"/api/items/{d['id']}/original", headers=viewer).status_code == 403
    before = db.query(AuditLog).filter(AuditLog.action == "item.view_original").count()
    orig = client.get(f"/api/items/{d['id']}/original", headers=operator)
    assert orig.status_code == 200
    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.action == "item.view_original").count() == before + 1


def test_pii_never_in_list_or_export(client, operator):
    r = client.get("/api/items", params={"is_direct": "true", "page_size": 100}, headers=operator).json()
    blob = str(r)
    for secret in ["850312300123", "+7 701 234 56 78", "aidar.k@example.com", "Сейткали"]:
        assert secret not in blob
    csv = client.get("/api/export/items.csv", params={"is_direct": "true"}, headers=operator).text
    assert "850312300123" not in csv and "Сейткали" not in csv


def test_correction_is_recorded_and_keeps_model_output(client, operator, db):
    item = client.get("/api/items", params={"department": "housing", "page_size": 1}, headers=operator).json()["items"][0]
    r = client.patch(f"/api/items/{item['id']}", json={"department": "improvement", "comment": "двор"}, headers=operator)
    assert r.status_code == 200
    e = r.json()["enrichment"]
    assert e["primary_department"] == "improvement" and e["model_department"] == "housing" and e["reviewed"]
    assert db.scalar(select(Correction).where(Correction.item_id == item["id"])) is not None
    assert client.patch(f"/api/items/{item['id']}", json={"department": "housing"},
                        headers=client.headers).status_code == 401


def test_viewer_cannot_correct(client, viewer):
    assert client.patch("/api/items/1", json={"sentiment": "positive"}, headers=viewer).status_code == 403


def test_clusters_and_status_propagation(client, operator, db):
    cl = client.get("/api/clusters", headers=operator).json()
    assert cl["total"] >= 5
    top = cl["items"][0]
    assert top["priority_factors"]["terms"]["negativity"]["max"] == 25
    detail = client.get(f"/api/clusters/{top['id']}", headers=operator).json()
    assert len(detail["items"]) >= 1 and detail["timeline"]
    r = client.patch(f"/api/clusters/{top['id']}", json={"status": "transferred"}, headers=operator)
    assert r.status_code == 200 and r.json()["status"] == "transferred"
    ids = [i["id"] for i in r.json()["items"]]
    db.expire_all()
    assert all(db.get(Item, i).status == "transferred" and db.get(Item, i).transferred_at for i in ids)


def test_dashboards(client, operator):
    ov = client.get("/api/stats/overview", params={"days": 30}, headers=operator).json()
    k = ov["kpis"]
    assert k["total"] > 50 and -100 <= k["mood_index"] <= 100
    assert sum(ov["sentiment"].values()) == k["total"]
    assert ov["top_problems"] and ov["daily"] and ov["by_department"]
    dp = client.get("/api/stats/departments", headers=operator).json()
    assert dp["departments"] and "rating" in dp["departments"][0]
    ops = client.get("/api/stats/operations", headers=operator).json()
    assert "review_queue" in ops


def test_department_scope(client, admin):
    r = client.post("/api/users", json={"login": "roads_head", "full_name": "Начальник дорог", "password": "roads12345",
                                        "role": "viewer", "department_code": "roads"}, headers=admin)
    assert r.status_code == 200
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"login": "roads_head", "password": "roads12345"}).json()["token"]}
    items = client.get("/api/items", params={"page_size": 200}, headers=h).json()["items"]
    assert items and all(i["enrichment"]["primary_department"] == "roads" for i in items)
    assert all(c["department"] == "roads" for c in client.get("/api/clusters", headers=h).json()["items"])


def test_exports(client, operator, viewer):
    csv = client.get("/api/export/items.csv", params={"department": "roads"}, headers=operator)
    assert csv.status_code == 200 and "Дороги и транспорт" in csv.text
    x = client.get("/api/export/items.xlsx", params={"sentiment": "negative"}, headers=operator)
    wb = load_workbook(io.BytesIO(x.content))
    assert wb.active.max_row > 10
    for url in ["/api/export/items.pdf", "/api/export/clusters.pdf", "/api/export/report.pdf", "/api/export/clusters.xlsx"]:
        r = client.get(url, headers=operator)
        assert r.status_code == 200 and len(r.content) > 1000, url
    assert client.get("/api/export/items.pdf", headers=operator).content[:4] == b"%PDF"
    # viewer export excludes Direct
    vcsv = client.get("/api/export/items.csv", headers=viewer).text
    assert ";да;" not in vcsv


def test_upload_and_dedup(client, operator):
    data = "text,date\nНа ул. Сатпаева упало дерево на провода,2026-10-29 10:00\nНа ул. Сатпаева упало дерево на провода,2026-10-29 10:00\n"
    r = client.post("/api/upload", files={"file": ("t.csv", data.encode(), "text/csv")},
                    data={"source_name": "Тестовая выгрузка"}, headers=operator)
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == 2 and r.json()["new_items"] == 1
    bad = client.post("/api/upload", files={"file": ("t.csv", b"foo,bar\n1,2\n", "text/csv")}, headers=operator)
    assert bad.status_code == 400 and "текстом" in bad.json()["detail"]


def test_quality_labeling_and_eval(client, operator):
    q = client.get("/api/quality/labeling", params={"origin": "synthetic", "limit": 5}, headers=operator).json()
    assert q["items"] and "enrichment" not in q["items"][0]          # blind labelling
    for it in q["items"]:
        assert client.put(f"/api/quality/gold/{it['id']}", json={"department": "housing", "sentiment": "negative"},
                          headers=operator).status_code == 200
    r = client.post("/api/quality/evaluate", json={"split": "all", "origin": "synthetic"}, headers=operator)
    assert r.status_code == 200 and r.json()["n"] >= 5
    none = client.post("/api/quality/evaluate", json={"split": "test", "origin": "real"}, headers=operator)
    assert none.status_code == 400


def test_assistant_without_llm(client, operator):
    r = client.post("/api/assistant/ask", json={"question": "Какие главные жалобы по ЖКХ за последнюю неделю?"},
                    headers=operator).json()
    assert r["filters"].get("department") == "housing" and r["items"] and "[" in r["answer"]
    d = client.get("/api/assistant/digest", params={"department": "housing"}, headers=operator).json()
    assert d["text"]


def test_delete_on_request(client, admin, operator):
    item = client.get("/api/items", params={"page_size": 1, "sort": "date_asc"}, headers=admin).json()["items"][0]
    assert client.delete(f"/api/items/{item['id']}", headers=operator).status_code == 403
    assert client.delete(f"/api/items/{item['id']}", headers=admin).status_code == 200
    assert client.get(f"/api/items/{item['id']}", headers=admin).status_code == 404
