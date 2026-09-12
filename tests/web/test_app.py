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


def test_submit_url_strips_tracking_params(tmp_path):
    c, db_path = make_client(tmp_path)
    c.post("/products", data={
        "url": "https://detail.1688.com/offer/9.html?spm=a26352.1&uuid=xyz#frag"})
    conn = get_conn(db_path)
    saved = conn.execute("SELECT source_url FROM products").fetchone()["source_url"]
    assert saved == "https://detail.1688.com/offer/9.html"


def test_kanban_shows_failed_job_with_retry(tmp_path):
    c, db_path = make_client(tmp_path)
    c.post("/products", data={"url": "https://detail.1688.com/offer/9.html"})
    conn = get_conn(db_path)
    conn.execute("INSERT INTO jobs(type, payload_json, status, retries, error) "
                 "VALUES('collect', '{\"product_id\": 1}', 'failed', 3, 'boom')")
    conn.commit()
    html = c.get("/").text
    assert "boom" in html
    jid = conn.execute("SELECT id FROM jobs WHERE status='failed'").fetchone()["id"]
    assert f"/jobs/{jid}/retry" in html
    assert c.post(f"/jobs/{jid}/retry", follow_redirects=False).status_code == 303
    assert conn.execute("SELECT status FROM jobs").fetchone()["status"] == "queued"


def test_kanban_shows_groups(tmp_path):
    c, _ = make_client(tmp_path)
    c.post("/products", data={"url": "https://detail.1688.com/offer/9.html"})
    assert "待处理" in c.get("/").text


def test_startup_reaps_stale_running_jobs(tmp_path):
    db_path = str(tmp_path / "r.db")
    init_db(db_path)
    conn = get_conn(db_path)
    conn.execute("INSERT INTO jobs(type, payload_json, status) VALUES('generate', '{}', 'running')")
    conn.commit()
    ctx = SimpleNamespace(settings=Settings(_env_file=None), db_path=db_path)
    create_app(ctx, run_worker=False)
    assert conn.execute("SELECT status FROM jobs").fetchone()["status"] == "queued"


def test_delete_product_removes_all(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    c.post("/products/import-html", files=files)
    assert c.post("/products/1/delete", follow_redirects=False).status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM source_snapshots").fetchone()[0] == 0
    assert c.get("/products/1").status_code == 404


def test_cors_preflight_allows_1688_extension(tmp_path):
    c, _ = make_client(tmp_path)
    r = c.options("/products/import-json", headers={
        "Origin": "https://detail.1688.com",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Private-Network": "true"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-private-network"] == "true"
    assert "POST" in r.headers["access-control-allow-methods"]


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


def test_edit_toggles_image_selected(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    c.post("/products/import-html", files=files)
    conn = get_conn(db_path)
    conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(1, 'main', 'https://img/a.jpg')")
    conn.commit()
    base = {"title_ru": "T", "description_ru": "D", "price_rub": "",
            "ozon_category_id": "42", "attributes_json": "[]"}
    c.post("/products/1/edit", data={**base, "sel_1": "1"})
    assert conn.execute("SELECT selected FROM images WHERE id=1").fetchone()["selected"] == 1
    c.post("/products/1/edit", data=base)
    assert conn.execute("SELECT selected FROM images WHERE id=1").fetchone()["selected"] == 0


def test_regenerate_single_image_enqueues_job(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    c.post("/products/import-html", files=files)
    conn = get_conn(db_path)
    conn.execute("INSERT INTO images(product_id, kind, source_url, translated_url, status) "
                 "VALUES(1, 'main', 'https://img/a.jpg', 'https://r2/a.png', 'uploaded')")
    conn.commit()
    r = c.post("/products/1/images/1/regenerate", data={"prompt_override": "只去logo"},
               follow_redirects=False)
    assert r.status_code == 303
    job = conn.execute("SELECT type, payload_json FROM jobs WHERE type='regenerate_image'").fetchone()
    assert job is not None
    import json as _j
    assert _j.loads(job[1]) == {"product_id": 1, "image_id": 1, "prompt_override": "只去logo"}


def test_review_shows_spinner_and_autorefresh_when_generating(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    c.post("/products/import-html", files=files)
    conn = get_conn(db_path)
    conn.execute("INSERT INTO images(product_id, kind, source_url, status) "
                 "VALUES(1, 'main', 'https://img/a.jpg', 'pending')")
    conn.execute("UPDATE products SET status='generating' WHERE id=1")
    conn.commit()
    html = c.get("/products/1").text
    assert "spinner" in html
    assert "生成中" in html
    assert "location.reload" in html


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


def _insert_product(db_path, status: str) -> None:
    conn = get_conn(db_path)
    conn.execute(
        "INSERT INTO products (source_url, status) VALUES (?, ?)",
        ("https://detail.1688.com/offer/1.html", status),
    )
    conn.commit()


def test_approve_wrong_status_returns_400(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "new")
    r = c.post("/products/1/approve", follow_redirects=False)
    assert r.status_code == 400


def test_regenerate_wrong_status_returns_400(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "new")
    r = c.post("/products/1/regenerate", follow_redirects=False)
    assert r.status_code == 400


def test_approve_from_listed_and_failed_allowed(tmp_path):
    c, db_path = make_client(tmp_path)
    for st in ("listed", "failed"):
        _insert_product(db_path, st)
        r = c.post("/products/1/approve", follow_redirects=False)
        assert r.status_code == 303
        conn = get_conn(db_path)
        conn.execute("DELETE FROM products WHERE id=1")
        conn.execute("DELETE FROM jobs WHERE payload_json LIKE '%\"product_id\": 1%'")
        conn.commit()


def test_publish_batch_enqueues_selected(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO products(id, source_url, status) VALUES(2, 'https://x/2', 'listed')")
    conn.commit()
    r = c.post("/products/publish-batch", data={"pid": ["1", "2", "zzz"]},
               follow_redirects=False)
    assert r.status_code == 303
    n = conn.execute("SELECT count(*) FROM jobs WHERE type='publish'").fetchone()[0]
    assert n == 2
    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "publishing"


def test_kanban_shows_title_and_thumb(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'title', '手表带', 'Ремешок для часов')")
    conn.execute("INSERT INTO images(product_id, kind, source_url, translated_url, status) "
                 "VALUES(1, 'main', 'https://img/a.jpg', 'https://r2/a.png', 'uploaded')")
    conn.commit()
    html = c.get("/").text
    assert "Ремешок для часов" in html
    assert "https://r2/a.png" in html


def test_review_shows_video_and_rich_content(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("UPDATE products SET video_url='https://r2/v.mp4', "
                 "rich_content='{\"version\": 0.3}' WHERE id=1")
    conn.commit()
    html = c.get("/products/1").text
    assert "https://r2/v.mp4" in html
    assert "rich_content" in html


def test_edit_saves_rich_content(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    r = c.post("/products/1/edit", data={
        "title_ru": "T", "description_ru": "D", "ozon_category_id": "42",
        "attributes_json": "[]", "rich_content": '{"version": 0.3, "content": []}',
    }, follow_redirects=False)
    assert r.status_code == 303
    conn = get_conn(db_path)
    saved = conn.execute("SELECT rich_content FROM products WHERE id=1").fetchone()[0]
    assert saved == '{"version": 0.3, "content": []}'


def test_content_regenerate_routes_enqueue_jobs(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    assert c.post("/products/1/content/video/regenerate",
                  follow_redirects=False).status_code == 303
    assert c.post("/products/1/content/rich/regenerate",
                  follow_redirects=False).status_code == 303
    conn = get_conn(db_path)
    types = {r["type"] for r in conn.execute("SELECT type FROM jobs")}
    assert {"regenerate_video", "regenerate_rich"} <= types
    assert c.post("/products/9/content/video/regenerate",
                  follow_redirects=False).status_code == 404


def test_kanban_status_filter_and_counts(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO products(id, source_url, status) VALUES(2, 'https://x/2', 'listed')")
    conn.commit()
    html = c.get("/").text
    assert "待审" in html and "已上架" in html
    listed = c.get("/?status=listed").text
    assert "https://x/2" in listed or "#2" in listed
    assert "/?status=review" in html


def test_edit_rebuilds_rich_from_visual_blocks(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    r = c.post("/products/1/edit", data={
        "title_ru": "T", "description_ru": "D", "ozon_category_id": "42",
        "attributes_json": "[]", "rc_count": "2",
        "rc_img_0": "https://r2/a.png", "rc_title_0": "Заголовок",
        "rc_text_0": "Текст 1",
        "rc_img_1": "https://r2/b.png", "rc_title_1": "Ещё",
        "rc_text_1": "Текст 2",
    }, follow_redirects=False)
    assert r.status_code == 303
    conn = get_conn(db_path)
    import json as _j
    rich = _j.loads(conn.execute("SELECT rich_content FROM products WHERE id=1").fetchone()[0])
    blocks = rich["content"][0]["blocks"]
    assert len(blocks) == 2
    assert blocks[0]["img"]["src"] == "https://r2/a.png"
    assert blocks[0]["title"]["content"][0] == "Заголовок"


def test_edit_rejects_invalid_raw_rich_json(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    r = c.post("/products/1/edit", data={
        "title_ru": "T", "description_ru": "D", "ozon_category_id": "42",
        "attributes_json": "[]", "rc_raw_mode": "1", "rich_content": "{bad json",
    }, follow_redirects=False)
    assert r.status_code == 400


def test_review_shows_title_candidates_and_warnings(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO title_candidates(product_id, style, ru) "
                 "VALUES(1, 'seo', 'Нейлоновый ремешок для Apple Watch')")
    conn.execute("INSERT INTO translations(product_id, field, ru) VALUES(1, 'title', 'Коротко')")
    conn.commit()
    html = c.get("/products/1").text
    assert "Нейлоновый ремешок для Apple Watch" in html
    assert "SEO 覆盖型" in html
    assert "warnbox" in html and "过短" in html


def test_titles_regenerate_route_enqueues(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    assert c.post("/products/1/titles/regenerate",
                  follow_redirects=False).status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='regenerate_titles'"
                        ).fetchone()[0] == 1
    assert c.post("/products/9/titles/regenerate",
                  follow_redirects=False).status_code == 404


def test_keywords_fetch_route_and_display(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    assert c.post("/products/1/keywords/fetch", follow_redirects=False).status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='fetch_keywords'"
                        ).fetchone()[0] == 1
    conn.execute("UPDATE products SET keywords='[\"ремешок для часов\"]' WHERE id=1")
    conn.commit()
    html = c.get("/products/1").text
    assert "已抓取搜索词" in html and "ремешок для часов" in html


def test_edit_uses_title_pick_when_title_empty(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO title_candidates(product_id, style, ru) "
                 "VALUES(1, 'seo', 'Выбранный заголовок для часов')")
    conn.commit()
    cid = conn.execute("SELECT id FROM title_candidates").fetchone()[0]
    r = c.post("/products/1/edit", data={
        "title_ru": "", "description_ru": "D", "ozon_category_id": "42",
        "attributes_json": "[]", "title_pick": str(cid),
    }, follow_redirects=False)
    assert r.status_code == 303
    saved = conn.execute("SELECT ru FROM translations WHERE product_id=1 AND field='title'"
                         ).fetchone()["ru"]
    assert saved == "Выбранный заголовок для часов"


def test_media_proxy_rejects_bad_url(tmp_path):
    c, _ = make_client(tmp_path)
    assert c.get("/media/proxy").status_code == 400
    assert c.get("/media/proxy?u=file:///etc/passwd").status_code == 400
    assert c.get("/media/proxy?u=not-a-url").status_code == 400


def test_review_uses_media_proxy_for_source_images(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO images(product_id, kind, source_url, status) "
                 "VALUES(1, 'main', 'https://cbu01.alicdn.com/img/a.jpg', 'pending')")
    conn.commit()
    html = c.get("/products/1").text
    assert "/media/proxy?u=https%3A//cbu01.alicdn.com/img/a.jpg" in html


def test_review_proxies_external_translated_images(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO images(product_id, kind, source_url, translated_url, status) "
                 "VALUES(1, 'main', 'https://cbu01.alicdn.com/img/a.jpg', "
                 "'https://cbu01.alicdn.com/img/a.jpg', 'uploaded')")
    conn.commit()
    html = c.get("/products/1").text
    assert html.count("/media/proxy?u=https%3A//cbu01.alicdn.com/img/a.jpg") == 2
    assert "无文字，用原图" in html


def test_review_inline_source_text_and_variant_grid(tmp_path):
    import json

    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'title', '手表带', 'Ремешок')")
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'description', '中文描述内容', 'Описание')")
    conn.execute("INSERT INTO settings_kv(key, value) VALUES('cny_rub_rate', '12.0')")
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(1, ?)",
                 (json.dumps({"source_url": "u", "platform": "1688", "title_zh": "手表带",
                              "price_cny": 5.0,
                              "skus": [{"props": {"颜色": "黑色"}, "price_cny": 5.0},
                                       {"props": {"颜色": "红色"}, "price_cny": 6.0}]}),
                  ))
    conn.execute("INSERT INTO sku_options(product_id, option_zh, option_ru, attr_id, "
                 "dict_value_id) VALUES(1, '黑色', 'черный', 10096, 61574)")
    conn.execute("INSERT INTO sku_options(product_id, option_zh, option_ru, attr_id) "
                 "VALUES(1, '红色', 'красный', 10096)")
    conn.commit()
    html = c.get("/products/1").text
    assert "原文：手表带" in html              # 标题随文对照
    assert "查看中文原文" in html               # 描述折叠对照
    assert "черный" in html and "✓ 词典" in html  # 变体网格 + 词典命中
    assert "красный" in html and "文本" in html    # 未命中词典的提示


def test_edit_preserves_chinese_source(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'title', '原文标题', 'Старый заголовок')")
    conn.commit()
    c.post("/products/1/edit", data={
        "title_ru": "Новый заголовок", "description_ru": "D",
        "ozon_category_id": "42", "attributes_json": "[]",
    })
    row = conn.execute("SELECT zh, ru FROM translations WHERE product_id=1 AND field='title'"
                       ).fetchone()
    assert row["zh"] == "原文标题"          # 中文原文不被清空
    assert row["ru"] == "Новый заголовок"


def test_review_backfills_source_text_from_snapshot(tmp_path):
    import json

    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO translations(product_id, field, zh, ru) "
                 "VALUES(1, 'title', '', 'Ремешок')")
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(1, ?)",
                 (json.dumps({"source_url": "u", "platform": "1688",
                              "title_zh": "尼龙表带", "description_zh": "描述文本",
                              "skus": []}),))
    conn.commit()
    html = c.get("/products/1").text
    assert "原文：尼龙表带" in html
    assert "描述文本" in html


def test_review_shows_pricing_and_preflight(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    conn.execute("UPDATE products SET price_rub=50, stock=10 WHERE id=1")
    conn.commit()
    html = c.get("/products/1").text
    assert "保本价" in html and "建议价" in html
    assert "发布前检查" in html


def test_dashboard_and_jobs_pages_render(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "listed")
    conn = get_conn(db_path)
    conn.execute("INSERT INTO metrics(product_id, sku, rating, price, stock, availability, reason) "
                 "VALUES(1, '123', 100, 75, 10, 'AVAILABLE', '')")
    conn.commit()
    html = c.get("/dashboard").text
    assert "运营看板" in html and "rating-good" in html
    jobs_html = c.get("/jobs").text
    assert "任务中心" in jobs_html and "服务日志" in jobs_html
    assert c.post("/dashboard/refresh", follow_redirects=False).status_code == 303
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='refresh_metrics'"
                        ).fetchone()[0] == 1


def test_submit_multiple_urls_and_dedupe(tmp_path):
    c, db_path = make_client(tmp_path)
    c.post("/products", data={"url": "https://detail.1688.com/offer/1.html\n"
                                      "https://detail.1688.com/offer/2.html\ninvalid"})
    conn = get_conn(db_path)
    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='collect'").fetchone()[0] == 2
    c.post("/products", data={"url": "https://detail.1688.com/offer/1.html"})
    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 2


def test_kanban_search_and_pagination(tmp_path):
    c, db_path = make_client(tmp_path)
    conn = get_conn(db_path)
    for i in range(1, 31):
        conn.execute("INSERT INTO products(id, source_url, status) VALUES(?,?, 'review')",
                     (i, f"https://detail.1688.com/offer/{i}.html"))
    conn.execute("INSERT INTO translations(product_id, field, ru) VALUES(3, 'title', 'Искомый товар')")
    conn.commit()
    html = c.get("/?q=Искомый").text
    assert "Искомый товар" in html
    assert "offer/1.html" not in html  # 只显示匹配结果
    page2 = c.get("/?page=2").text
    assert "上一页" in page2
    assert "下一页" in c.get("/?page=1").text


def test_infographic_and_improve_routes(tmp_path):
    c, db_path = make_client(tmp_path)
    _insert_product(db_path, "review")
    conn = get_conn(db_path)
    assert c.post("/products/1/infographic", follow_redirects=False).status_code == 303
    assert c.post("/products/1/description/improve",
                  follow_redirects=False).status_code == 303
    types = {r["type"] for r in conn.execute("SELECT type FROM jobs")}
    assert {"make_infographic", "improve_description"} <= types
    html = c.get("/products/1").text
    assert "生成首图信息图" in html and "AI 优化描述" in html


def test_promotions_pages_and_actions(tmp_path):
    import json as _j

    c, db_path = make_client(tmp_path)
    conn = get_conn(db_path)
    conn.execute("INSERT INTO promotions(action_id, title, date_start, date_end, potential) "
                 "VALUES(1977747, 'Эластичный бустинг', '2026-01-01', '2026-12-31', 10)")
    conn.execute("INSERT INTO promotion_candidates(action_id, product_id, price, "
                 "max_action_price, stock, image_url, participating, action_price) "
                 "VALUES(1977747, '558174716', 40, 38, 5, 'https://ir.ozone.ru/x.jpg', 1, 36)")
    conn.commit()
    html = c.get("/promotions").text
    assert "Эластичный бустинг" in html and "查看商品" in html
    detail = c.get("/promotions/1977747").text
    assert "558174716" in detail and "保本价" in detail and "参加选中" in detail
    assert 'src="https://ir.ozone.ru/x.jpg"' in detail
    assert "已参加" in detail
    r = c.post("/promotions/1977747/activate",
               data={"sel_558174716": "1", "price_558174716": "36"},
               follow_redirects=False)
    assert r.status_code == 303
    job = conn.execute("SELECT payload_json FROM jobs WHERE type='promotion_activate'"
                       ).fetchone()
    payload = _j.loads(job["payload_json"])
    assert payload["products"] == [{"product_id": 558174716, "action_price": 36.0}]
    r2 = c.post("/promotions/1977747/deactivate", data={"sel_558174716": "1"},
                follow_redirects=False)
    assert r2.status_code == 303
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='promotion_deactivate'"
                        ).fetchone()[0] == 1
    assert c.get("/promotions/999").status_code == 404
