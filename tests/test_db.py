from openoctopus.db import get_conn, init_db
from openoctopus.models import RawProduct

TABLES = {"products", "source_snapshots", "translations", "images",
          "category_mappings", "jobs", "listings", "ozon_categories"}


def test_init_db_creates_tables(tmp_path):
    p = tmp_path / "t.db"
    init_db(str(p))
    conn = get_conn(str(p))
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_product_insert_and_status(tmp_path):
    p = tmp_path / "t.db"
    init_db(str(p))
    conn = get_conn(str(p))
    conn.execute("INSERT INTO products(source_url, platform, status) VALUES('https://detail.1688.com/offer/123.html','1688','new')")
    row = dict(conn.execute("SELECT * FROM products").fetchone())
    assert row["status"] == "new"


def test_models_defaults():
    rp = RawProduct(source_url="u", platform="1688", title_zh="T")
    assert rp.main_images == [] and rp.skus == []
