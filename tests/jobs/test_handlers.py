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
        self.price_calls = []

    async def import_products(self, items):
        self.received_items = items
        return {"result": {"task_id": 1}}

    async def import_task_info(self, task_id):
        self.received_task_id = task_id
        return {"result": {"items": [{"status": "exported", "product_id": 99}]}}

    async def update_price(self, product_id, price, old_price=None):
        self.price_calls.append((product_id, price))
        return {}


def make_publish_ctx(tmp_path):
    db_path = str(tmp_path / "p.db")
    init_db(db_path)
    settings = SimpleNamespace(price_cny_to_rub=12.0, price_currency="RUB")
    return SimpleNamespace(db_path=db_path, settings=settings, ozon=FakeOzon())


async def test_publish_sends_items_list_not_nested(tmp_path):
    ctx = make_publish_ctx(tmp_path)
    conn = get_conn(ctx.db_path)
    conn.execute(
        "INSERT INTO products(id, source_url, platform, status, price_rub) "
        "VALUES(1, 'https://detail.1688.com/offer/1.html', '1688', 'review', 1000)")
    conn.execute(
        "INSERT INTO category_mappings(product_id, ozon_category_id, type_id, attributes_json,"
        " human_confirmed) VALUES(1, '123', '456', '[]', 1)")
    conn.execute(
        "INSERT INTO translations(product_id, field, zh, ru) VALUES(1, 'title', '杯', 'Kruzhka')")
    conn.execute(
        "INSERT INTO images(product_id, kind, source_url, translated_url, status) "
        "VALUES(1, 'main', 'https://img/a.jpg', 'https://cdn/a.png', 'uploaded')")
    conn.execute(
        "INSERT INTO source_snapshots(product_id, raw_json) VALUES(1, ?)",
        (json.dumps(dict(SNAPSHOT, skus=[])),))
    conn.commit()

    await handle_publish(ctx, {"product_id": 1})

    assert isinstance(ctx.ozon.received_items, list)
    assert not (isinstance(ctx.ozon.received_items, dict) and "items" in ctx.ozon.received_items)
    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "listed"
    listing = conn.execute("SELECT * FROM listings WHERE product_id=1").fetchone()
    assert listing["import_task_id"] == "1"


async def test_publish_all_skipped_counts_as_listed(tmp_path):
    import json as _json

    class SkipOzon(FakeOzon):
        async def import_task_info(self, task_id):
            return {"result": {"items": [
                {"offer_id": "1-1", "status": "skipped"},
                {"offer_id": "1-2", "status": "skipped"}]}}

    db_path = str(tmp_path / "s.db")
    init_db(db_path)
    from types import SimpleNamespace
    ctx = SimpleNamespace(db_path=db_path, settings=None, ozon=SkipOzon())
    conn = get_conn(ctx.db_path)
    conn.execute(
        "INSERT INTO products(id, source_url, platform, status, price_rub) "
        "VALUES(1, 'https://detail.1688.com/offer/1.html', '1688', 'review', 100)")
    conn.execute(
        "INSERT INTO category_mappings(product_id, ozon_category_id, type_id, attributes_json,"
        " human_confirmed) VALUES(1, '123', '456', '[]', 1)")
    conn.execute(
        "INSERT INTO translations(product_id, field, zh, ru) VALUES(1, 'title', '杯', 'Kruzhka')")
    conn.execute(
        "INSERT INTO images(product_id, kind, source_url, translated_url, status) "
        "VALUES(1, 'main', 'https://img/a.jpg', 'https://cdn/a.png', 'uploaded')")
    conn.execute(
        "INSERT INTO source_snapshots(product_id, raw_json) VALUES(1, ?)",
        (_json.dumps({"source_url": "u", "platform": "1688", "title_zh": "T",
                      "price_cny": 10, "skus": []}),))
    conn.commit()

    await handle_publish(ctx, {"product_id": 1})

    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "listed"
    res = _json.loads(conn.execute("SELECT result_json FROM listings").fetchone()[0])
    assert res["status"] == "skipped"
    assert len(res["items"]) == 2


async def test_publish_price_sync_uses_ozon_pid(tmp_path):
    ctx = make_publish_ctx(tmp_path)
    conn = get_conn(ctx.db_path)
    conn.execute(
        "INSERT INTO products(id, source_url, platform, status, price_rub) "
        "VALUES(1, 'https://detail.1688.com/offer/1.html', '1688', 'review', 1000)")
    conn.execute(
        "INSERT INTO category_mappings(product_id, ozon_category_id, type_id, attributes_json,"
        " human_confirmed) VALUES(1, '123', '456', '[]', 1)")
    conn.execute(
        "INSERT INTO translations(product_id, field, zh, ru) VALUES(1, 'title', '杯', 'Kruzhka')")
    conn.execute(
        "INSERT INTO images(product_id, kind, source_url, translated_url, status) "
        "VALUES(1, 'main', 'https://img/a.jpg', 'https://cdn/a.png', 'uploaded')")
    conn.execute(
        "INSERT INTO source_snapshots(product_id, raw_json) VALUES(1, ?)",
        (json.dumps({"source_url": "u", "platform": "1688", "title_zh": "T",
                     "price_cny": 10, "skus": []}),))
    conn.commit()

    await handle_publish(ctx, {"product_id": 1})

    assert ctx.ozon.price_calls and ctx.ozon.price_calls[0][0] == 99
    assert ctx.ozon.price_calls[0][1] == 1000.0


async def test_publish_variants_multi_items(tmp_path):
    ctx = make_publish_ctx(tmp_path)
    conn = get_conn(ctx.db_path)
    conn.execute(
        "INSERT INTO products(id, source_url, platform, status, price_rub) "
        "VALUES(1, 'https://detail.1688.com/offer/1.html', '1688', 'review', 1000)")
    conn.execute(
        "INSERT INTO category_mappings(product_id, ozon_category_id, type_id, attributes_json,"
        " human_confirmed) VALUES(1, '123', '456', '[]', 1)")
    conn.execute(
        "INSERT INTO translations(product_id, field, zh, ru) VALUES(1, 'title', '杯', 'Kruzhka')")
    conn.execute(
        "INSERT INTO images(product_id, kind, source_url, translated_url, status) "
        "VALUES(1, 'main', 'https://img/a.jpg', 'https://cdn/a.png', 'uploaded')")
    snap = dict(SNAPSHOT, skus=[
        {"props": {"颜色": "红色"}, "price_cny": 10.0, "image_url": None},
        {"props": {"颜色": "蓝色"}, "price_cny": 12.0, "image_url": None}])
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(1, ?)",
                 (json.dumps(snap),))
    conn.execute(
        "INSERT INTO sku_options(product_id, option_zh, option_ru, attr_id, dict_value_id) VALUES "
        "(1, '红色', 'Красный', 85, 7), (1, '蓝色', 'Синий', 85, NULL)")
    conn.commit()

    await handle_publish(ctx, {"product_id": 1})

    items = ctx.ozon.received_items
    assert [i["offer_id"] for i in items] == ["1-1", "1-2"]
    # 用户设了 price_rub=1000，所有变体统一用这个价格
    assert [i["price"] for i in items] == ["1000.0", "1000.0"]
    assert 9048 in [a["id"] for a in items[0]["attributes"]]
    assert 9048 in [a["id"] for a in items[1]["attributes"]]
    assert items[0]["attributes"][-2] == {"complex_id": 0, "id": 85,
                                          "values": [{"dictionary_value_id": 7}]}
    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "listed"


async def test_content_assets_reuses_stored_values(tmp_path):
    from openoctopus.jobs.handlers import _content_assets

    ctx = make_publish_ctx(tmp_path)
    ctx.storage = None
    conn = get_conn(ctx.db_path)
    conn.execute("INSERT INTO products(id, source_url, platform, status, "
                 "video_url, rich_content) VALUES(1, 'u', '1688', 'review', "
                 "'https://r2/v.mp4', '{\"version\": 0.3}')")
    conn.commit()
    video_url, rich = _content_assets(ctx, conn, 1, title_ru="T", desc_ru="D",
                                      gallery_urls=["https://r2/a.png", "https://r2/b.png"],
                                      title_zh="")
    assert video_url == "https://r2/v.mp4"
    assert rich == '{"version": 0.3}'


async def test_regenerate_rich_writes_json(tmp_path):
    from openoctopus.jobs.handlers import handle_regenerate_rich

    ctx = make_publish_ctx(tmp_path)
    ctx.storage = None
    conn = get_conn(ctx.db_path)
    conn.execute("INSERT INTO products(id, source_url, platform, status, "
                 "video_url) VALUES(1, 'u', '1688', 'review', 'https://r2/v.mp4')")
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'title', '带', 'Ремешок')")
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'description', '描述', 'Описание товара')")
    for i in (1, 2, 3):
        conn.execute("INSERT INTO images(product_id, kind, source_url, translated_url, status, "
                     "selected) VALUES(1, 'main', ?, ?, 'uploaded', 1)",
                     (f"https://img/{i}.jpg", f"https://r2/{i}.png"))
    conn.commit()
    await handle_regenerate_rich(ctx, {"product_id": 1})
    saved = conn.execute("SELECT rich_content FROM products WHERE id=1").fetchone()[0]
    assert "raShowcase" in saved


async def test_generate_title_candidates_fallback(tmp_path):
    from openoctopus.jobs.handlers import _generate_title_candidates

    async def create(**_kw):
        raise RuntimeError("llm down")

    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    db_path = str(tmp_path / "t.db")
    init_db(db_path)
    ctx = SimpleNamespace(db_path=db_path,
                          settings=SimpleNamespace(content_model="m"), llm_client=llm)
    conn = get_conn(db_path)
    conn.execute("INSERT INTO products(id, source_url, platform, status) "
                 "VALUES(1, 'u', '1688', 'generating')")
    conn.commit()
    cands = await _generate_title_candidates(
        ctx, conn, 1, title_zh="尼龙编织表带适用苹果手表", title_ru="Черновой", desc_ru="d")
    assert len(cands) == 3
    assert "нейлоновый" in cands[0]["text"].lower()
    assert conn.execute("SELECT count(*) FROM title_candidates WHERE product_id=1"
                        ).fetchone()[0] == 3


async def test_regenerate_titles_writes_candidates(tmp_path):
    from openoctopus.jobs.handlers import handle_regenerate_titles

    async def create(**_kw):
        payload = ('{"titles":[{"style":"seo","text":"Ремешок А для часов"},'
                   '{"style":"short","text":"Ремешок Б"},{"style":"benefit","text":"Ремешок В"}]}')
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    db_path = str(tmp_path / "t2.db")
    init_db(db_path)
    ctx = SimpleNamespace(db_path=db_path,
                          settings=SimpleNamespace(content_model="m"), llm_client=llm)
    conn = get_conn(db_path)
    conn.execute("INSERT INTO products(id, source_url, platform, status) "
                 "VALUES(1, 'u', '1688', 'review')")
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(1, ?)",
                 (json.dumps({"source_url": "u", "platform": "1688", "title_zh": "表带",
                              "skus": []}),))
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'title', '表带', 'Черновой')")
    conn.commit()
    await handle_regenerate_titles(ctx, {"product_id": 1})
    rows = conn.execute("SELECT style, ru FROM title_candidates WHERE product_id=1"
                        ).fetchall()
    assert len(rows) == 3
    assert rows[0]["ru"] == "Ремешок А для часов"
    # 不覆盖当前标题
    assert conn.execute("SELECT ru FROM translations WHERE product_id=1 AND field='title'"
                        ).fetchone()["ru"] == "Черновой"


async def test_fetch_keywords_stores_and_regenerates(tmp_path, monkeypatch):
    from openoctopus.content import keywords as kw
    from openoctopus.jobs import handlers as h

    async def fake_fetch(query, proxy="", limit=10, timeout_ms=45000):
        assert proxy == "http://p:1"
        return ["Ремешок для Apple Watch нейлоновый", "Браслет для часов силиконовый"]

    monkeypatch.setattr(kw, "fetch_ozon_titles", fake_fetch)

    kw_payload = '{"keywords": ["ремешок для apple watch", "браслет для часов"]}'
    titles_payload = ('{"titles":[{"style":"seo","text":"Ремешок А"},'
                      '{"style":"short","text":"Ремешок Б"},'
                      '{"style":"benefit","text":"Ремешок В"}]}')

    async def create(**kwargs):
        system = kwargs["messages"][0]["content"]
        payload = kw_payload if "keywords" in system.lower() else titles_payload
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    db_path = str(tmp_path / "kw.db")
    init_db(db_path)
    ctx = SimpleNamespace(
        db_path=db_path, llm_client=llm,
        settings=SimpleNamespace(content_model="m", ozon_scrape_proxy="http://p:1"))
    conn = get_conn(db_path)
    conn.execute("INSERT INTO products(id, source_url, platform, status) "
                 "VALUES(1, 'u', '1688', 'review')")
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(1, ?)",
                 (json.dumps({"source_url": "u", "platform": "1688",
                              "title_zh": "表带", "skus": []}),))
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'title', '表带', 'Ремешок для Apple Watch')")
    conn.commit()

    await h.handle_fetch_keywords(ctx, {"product_id": 1})

    saved = conn.execute("SELECT keywords FROM products WHERE id=1").fetchone()[0]
    assert "ремешок для apple watch" in saved
    assert conn.execute("SELECT count(*) FROM title_candidates WHERE product_id=1"
                        ).fetchone()[0] == 3
