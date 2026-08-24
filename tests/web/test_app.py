from io import BytesIO
from types import SimpleNamespace

from fastapi.testclient import TestClient

from openoctopus.config import Settings
from openoctopus.db import get_conn, init_db
from openoctopus.web.app import create_app

PAGE = ("<html><head><meta property='og:title' content='测试杯'></head><body>"
        "<div class='price'>¥5</div><div class='content-detail'></div></body></html>")


def make_client(tmp_path):
    db_path = str(tmp_path / "w.db")
    init_db(db_path)
    ctx = SimpleNamespace(settings=Settings(_env_file=None), db_path=db_path)
    return TestClient(create_app(ctx, run_worker=False)), db_path


def test_submit_url_enqueues_collect(tmp_path):
    c, db_path = make_client(tmp_path)
    r = c.post("/products", data={"url": "https://detail.1688.com/offer/9.html"},
               follow_redirects=False)
    assert r.status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='collect'").fetchone()[0] == 1


def test_kanban_shows_groups(tmp_path):
    c, _ = make_client(tmp_path)
    c.post("/products", data={"url": "https://detail.1688.com/offer/9.html"})
    assert "待处理" in c.get("/").text


def test_import_html(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    assert c.post("/products/import-html", files=files, follow_redirects=False).status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT status FROM products").fetchone()["status"] == "collected"
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='generate'").fetchone()[0] == 1


def test_review_and_edit_flow(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    c.post("/products/import-html", files=files)
    assert c.get("/products/1").status_code == 200
    r = c.post("/products/1/edit", data={
        "title_ru": "Термос", "description_ru": "Описание", "price_rub": "150",
        "ozon_category_id": "42", "attributes_json": "[{\"id\":85,\"value\":\"Сталь\"}]",
    }, follow_redirects=False)
    assert r.status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT human_confirmed FROM category_mappings "
                        "WHERE product_id=1").fetchone()["human_confirmed"] == 1
    assert c.post("/products/1/approve", follow_redirects=False).status_code == 303
    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "publishing"


def test_edit_invalid_attributes_returns_400(tmp_path):
    c, _ = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    c.post("/products/import-html", files=files)
    r = c.post("/products/1/edit", data={
        "title_ru": "Термос", "description_ru": "Описание", "price_rub": "150",
        "ozon_category_id": "42", "attributes_json": "not-json",
    }, follow_redirects=False)
    assert r.status_code == 400


def test_edit_blank_price_rub_saves(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    c.post("/products/import-html", files=files)
    conn = get_conn(db_path)
    conn.execute("UPDATE products SET price_rub=NULL WHERE id=1")
    conn.commit()
    r = c.post("/products/1/edit", data={
        "title_ru": "Термос", "description_ru": "Описание", "price_rub": "",
        "ozon_category_id": "42", "attributes_json": "{}",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert conn.execute("SELECT human_confirmed FROM category_mappings "
                        "WHERE product_id=1").fetchone()["human_confirmed"] == 1
    assert conn.execute("SELECT price_rub FROM products WHERE id=1").fetchone()["price_rub"] is None


def test_review_missing_product_returns_404(tmp_path):
    c, _ = make_client(tmp_path)
    assert c.get("/products/99999").status_code == 404

    r = c.post("/products/1/edit", data={
        "title_ru": "x", "description_ru": "y", "price_rub": "bad",
        "ozon_category_id": "42", "attributes_json": "{}",
    }, follow_redirects=False)
    assert r.status_code == 400
