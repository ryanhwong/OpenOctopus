import json
from types import SimpleNamespace

from openoctopus.db import get_conn, init_db
from openoctopus.jobs.handlers import handle_collect, handle_publish

SNAPSHOT = {
    "source_url": "https://detail.1688.com/offer/1.html", "platform": "1688",
    "title_zh": "保温杯", "bullets_zh": ["大容量"], "description_zh": "好杯子",
    "price_cny": 12.5,
    "main_images": ["https://img/main1.jpg"],
    "detail_images": ["https://img/d1.jpg"], "skus": [],
}


class FakeAdapter:
    platform = "1688"

    @staticmethod
    def matches(url):
        return True

    async def fetch(self, url):
        from openoctopus.models import RawProduct
        return RawProduct(**SNAPSHOT)


def make_ctx(tmp_path):
    db_path = str(tmp_path / "h.db")
    init_db(db_path)
    return SimpleNamespace(db_path=db_path, adapters=[FakeAdapter()], settings=None)


async def test_collect_persists_and_enqueues_generate(tmp_path):
    ctx = make_ctx(tmp_path)
    conn = get_conn(ctx.db_path)
    conn.execute(
        "INSERT INTO products(id, source_url, platform, status) "
        "VALUES(1, 'https://detail.1688.com/offer/1.html', '1688', 'new')")
    conn.commit()

    await handle_collect(ctx, {"product_id": 1})

    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "collected"
    kinds = sorted(r["kind"] for r in conn.execute(
        "SELECT kind FROM images WHERE product_id=1").fetchall())
    assert kinds == ["detail", "main"]
    job = conn.execute("SELECT * FROM jobs WHERE type='generate'").fetchone()
    assert json.loads(job["payload_json"]) == {"product_id": 1}


class FakeOzon:
    def __init__(self):
        self.received_items = None
        self.received_task_id = None

    async def import_products(self, items):
        self.received_items = items
        return {"result": {"task_id": 1}}

    async def import_task_info(self, task_id):
        self.received_task_id = task_id
        return {"result": {"items": [{"status": "exported", "product_id": 99}]}}


def make_publish_ctx(tmp_path):
    db_path = str(tmp_path / "p.db")
    init_db(db_path)
    return SimpleNamespace(db_path=db_path, settings=None, ozon=FakeOzon())


async def test_publish_sends_items_list_not_nested(tmp_path):
    ctx = make_publish_ctx(tmp_path)
    conn = get_conn(ctx.db_path)
    conn.execute(
        "INSERT INTO products(id, source_url, platform, status, price_rub) "
        "VALUES(1, 'https://detail.1688.com/offer/1.html', '1688', 'review', 1000)")
    conn.execute(
        "INSERT INTO category_mappings(product_id, ozon_category_id, attributes_json, human_confirmed) "
        "VALUES(1, '123', '[]', 1)")
    conn.execute(
        "INSERT INTO translations(product_id, field, zh, ru) VALUES(1, 'title', '杯', 'Kruzhka')")
    conn.commit()

    await handle_publish(ctx, {"product_id": 1})

    assert isinstance(ctx.ozon.received_items, list)
    assert not (isinstance(ctx.ozon.received_items, dict) and "items" in ctx.ozon.received_items)
    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "listed"
    listing = conn.execute("SELECT * FROM listings WHERE product_id=1").fetchone()
    assert listing["import_task_id"] == "1"
