import json
from types import SimpleNamespace

from openoctopus.db import get_conn, init_db
from openoctopus.jobs.handlers import handle_collect

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
