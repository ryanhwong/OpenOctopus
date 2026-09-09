import asyncio
import json

from openoctopus.category.suggest import (
    fill_attributes,
    match_option_values,
    pick_category,
    translate_options,
)
from openoctopus.category.sync import sync_categories
from openoctopus.jobs.queue import enqueue
from openoctopus.listing.builder import build_import_payload
from openoctopus.models import RawProduct


async def handle_collect(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    prod = conn.execute("SELECT * FROM products WHERE id=?",
                        (payload["product_id"],)).fetchone()
    adapter = next(a for a in ctx.adapters if a.matches(prod["source_url"]))
    raw = await adapter.fetch(prod["source_url"])
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(?,?)",
                 (prod["id"], raw.model_dump_json()))
    for u in raw.main_images:
        conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(?,'main',?)",
                     (prod["id"], u))
    for u in raw.detail_images:
        conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(?,'detail',?)",
                     (prod["id"], u))
    seen_imgs = set(raw.main_images) | set(raw.detail_images)
    if raw.skus:
        from openoctopus.models import variant_dim_index

        di = variant_dim_index(raw)
        for s in raw.skus[:40]:
            u = s.image_url or ""
            if not u or u in seen_imgs:
                continue
            seen_imgs.add(u)
            vals = list(s.props.values())
            label = vals[di] if di < len(vals) else ""
            conn.execute("INSERT INTO images(product_id, kind, source_url, label) "
                         "VALUES(?,'swatch',?,?)", (prod["id"], u, label))
    conn.execute("UPDATE products SET status='collected', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 (prod["id"],))
    conn.commit()
    enqueue(conn, "generate", {"product_id": prod["id"]})


def upsert_translation(conn, pid, field_, zh, ru, model=""):
    conn.execute(
        "INSERT INTO translations(product_id, field, zh, ru, model) VALUES(?,?,?,?,?) "
        "ON CONFLICT(product_id, field) DO UPDATE SET zh=excluded.zh, ru=excluded.ru, "
        "model=excluded.model", (pid, field_, zh, ru, model))


async def handle_generate(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    s = ctx.settings
    conn = get_conn(ctx.db_path)
    pid = payload["product_id"]
    snap = conn.execute("SELECT raw_json FROM source_snapshots WHERE product_id=? ORDER BY id DESC",
                        (pid,)).fetchone()
    raw = RawProduct(**json.loads(snap["raw_json"]))

    tc = await ctx.content_translator.translate(raw)
    upsert_translation(conn, pid, "title", raw.title_zh, tc.title_ru, tc.model)
    upsert_translation(conn, pid, "bullets", "\n".join(raw.bullets_zh),
                       "\n".join(tc.bullets_ru), tc.model)
    upsert_translation(conn, pid, "description", raw.description_zh, tc.description_ru, tc.model)

    conn.commit()  # 先落盘文案，下面逐张提交，单图失败不挡整单
    for row in conn.execute("SELECT id, kind, source_url FROM images "
                            "WHERE product_id=? AND status='pending'", (pid,)).fetchall():
        key_hint = f"products/{pid}/{row['kind']}-{row['id']}"
        try:
            url = await ctx.image_translator.translate(row["source_url"], key_hint)
        except Exception as e:  # noqa: BLE001
            conn.execute("UPDATE images SET status='failed', meta_json=? WHERE id=?",
                         (json.dumps({"error": str(e)[:200]}, ensure_ascii=False), row["id"]))
        else:
            conn.execute("UPDATE images SET translated_url=?, status='uploaded' WHERE id=?",
                         (url, row["id"]))
        conn.commit()

    if s.live_mode and conn.execute(
            "SELECT count(*) FROM ozon_categories").fetchone()[0] == 0:
        tree = await ctx.ozon.category_tree()
        sync_categories(ctx.ozon, conn, tree)

    candidates = [{"id": r["id"], "title": r["title"]}
                  for r in conn.execute("SELECT id, title FROM ozon_categories "
                                        "WHERE id LIKE '%:%' ORDER BY title LIMIT 300")]
    cat_key = await pick_category(ctx.llm_client, s.content_model, candidates, raw, tc)
    if ":" not in cat_key:
        raise RuntimeError(f"LLM 未选中叶子类型（返回 {cat_key}），请在人审页手动指定")
    desc_id, type_id = cat_key.split(":", 1)
    schema_items = (await ctx.ozon.category_attributes(int(desc_id), int(type_id))
                    if s.live_mode else [])
    attrs = await fill_attributes(ctx.llm_client, s.content_model, schema_items, raw, tc)
    conn.execute(
        "INSERT INTO category_mappings(product_id, ozon_category_id, type_id, attributes_json)"
        " VALUES(?,?,?,?) "
        "ON CONFLICT(product_id) DO UPDATE SET ozon_category_id=excluded.ozon_category_id, "
        "type_id=excluded.type_id, "
        "attributes_json=excluded.attributes_json, human_confirmed=0",
        (pid, desc_id, type_id, json.dumps(attrs, ensure_ascii=False)))

    price = conn.execute("SELECT price_rub FROM products WHERE id=?", (pid,)).fetchone()["price_rub"]
    if price is None:
        if getattr(s, "price_currency", "RUB").upper() == "RUB":
            default_price = round(raw.price_cny * s.price_cny_to_rub)
        else:
            default_price = round(raw.price_cny, 2)
        conn.execute("UPDATE products SET price_rub=? WHERE id=?", (default_price, pid))
    if raw.skus:
        await _resolve_sku_options(ctx, conn, pid, raw, cat_key, schema_items)
    conn.execute("UPDATE products SET status='review', updated_at=CURRENT_TIMESTAMP WHERE id=?", (pid,))
    conn.commit()


async def _resolve_sku_options(ctx, conn, pid: int, raw, cat_key: str,
                               attrs_schema: list[dict]) -> None:
    from openoctopus.models import variant_dim_index

    s = ctx.settings
    dim_names = list(raw.skus[0].props.keys())
    dim = dim_names[variant_dim_index(raw)]
    options = sorted({sku.props[dim] for sku in raw.skus if dim in sku.props})
    opt_ru = await translate_options(ctx.llm_client, s.content_model, options)
    color_attr = next((a for a in attrs_schema
                       if "цвет" in str(a.get("name", "")).lower()), None)
    attr_id, matches = 0, {}
    if color_attr:
        attr_id = int(color_attr.get("id", 0))
        try:
            dict_vals = await ctx.ozon.category_attribute_values(
                attr_id, int(cat_key.split(":")[0]), int(cat_key.split(":")[1])) if s.live_mode else []
        except Exception:  # noqa: BLE001
            dict_vals = []
        matches = await match_option_values(
            ctx.llm_client, s.content_model,
            [opt_ru.get(o, o) for o in options], dict_vals)
    for o in options:
        ru = opt_ru.get(o, o)
        conn.execute(
            "INSERT INTO sku_options(product_id, option_zh, option_ru, attr_id, dict_value_id) "
            "VALUES(?,?,?,?,?) ON CONFLICT(product_id, option_zh) DO UPDATE SET "
            "option_ru=excluded.option_ru, attr_id=excluded.attr_id, "
            "dict_value_id=excluded.dict_value_id",
            (pid, o, ru, attr_id, matches.get(ru)))


async def handle_publish(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    pid = payload["product_id"]
    m = conn.execute("SELECT * FROM category_mappings WHERE product_id=?", (pid,)).fetchone()
    if not m or not m["human_confirmed"]:
        raise RuntimeError("类目与属性未经人工确认，禁止发布")
    if not (m["type_id"] or "").strip():
        raise RuntimeError("缺少叶子类型 type_id，请在人审页从候选选择具体类型后重试")
    t = {r["field"]: r["ru"] for r in conn.execute(
        "SELECT field, ru FROM translations WHERE product_id=?", (pid,))}
    main_urls = [r["translated_url"] or r["source_url"] for r in conn.execute(
        "SELECT kind, translated_url, source_url FROM images "
        "WHERE product_id=? AND kind='main' AND selected=1 ORDER BY id", (pid,))]
    detail_urls = [r["translated_url"] or r["source_url"] for r in conn.execute(
        "SELECT kind, translated_url, source_url FROM images "
        "WHERE product_id=? AND kind='detail' AND selected=1 ORDER BY id", (pid,))]
    if not main_urls:
        raise RuntimeError("没有选中上架图片，请在人审页至少勾选一张")
    gallery_urls = list(dict.fromkeys(main_urls + detail_urls))
    dims = {}
    dimrow = conn.execute("SELECT length_mm, width_mm, height_mm, weight_g FROM products "
                          "WHERE id=?", (pid,)).fetchone()
    if dimrow:
        dims = {k: dimrow[k] for k in ("length_mm", "width_mm", "height_mm", "weight_g")
                if dimrow[k]}
    dims_arg = {"length": dims["length_mm"], "width": dims["width_mm"],
                "height": dims["height_mm"], "weight": dims["weight_g"]} if len(dims) == 4 else None
    price = conn.execute("SELECT price_rub FROM products WHERE id=?", (pid,)).fetchone()["price_rub"]

    from openoctopus.listing.builder import build_variant_items
    from openoctopus.models import variant_dim_index

    snap = conn.execute("SELECT raw_json FROM source_snapshots WHERE product_id=? ORDER BY id DESC",
                        (pid,)).fetchone()
    raw_pub = RawProduct(**json.loads(snap["raw_json"])) if snap else None
    opt_map = {r["option_zh"]: dict(r) for r in
               conn.execute("SELECT * FROM sku_options WHERE product_id=?", (pid,))}
    base_attrs = json.loads(m["attributes_json"])
    title_ru, desc_ru = t["title"], t.get("description", "")
    desc_id, type_id = int(m["ozon_category_id"]), int(m["type_id"] or 0)
    if raw_pub and raw_pub.skus and opt_map:
        dim_names = list(raw_pub.skus[0].props.keys())
        dim = dim_names[variant_dim_index(raw_pub)]
        groups: dict[str, list] = {}
        for s in raw_pub.skus:
            if dim in s.props:
                groups.setdefault(s.props[dim], []).append(s)
        sw = {}
        for r in conn.execute("SELECT label, translated_url, source_url FROM images "
                              "WHERE product_id=? AND kind='swatch' AND selected=1", (pid,)):
            sw.setdefault(r["label"], []).append(r["translated_url"] or r["source_url"])
        variants = []
        for opt_zh, group in groups.items():
            o = opt_map.get(opt_zh, {})
            cny = min((g.price_cny for g in group if g.price_cny), default=0) or raw_pub.price_cny
            if getattr(ctx.settings, "price_currency", "RUB").upper() == "RUB":
                vprice = round(cny * ctx.settings.price_cny_to_rub)
            else:
                vprice = round(cny, 2)
            imgs = list(dict.fromkeys(sw.get(opt_zh, []) + gallery_urls))
            variants.append({
                "suffix": opt_zh,
                "price_rub": vprice,
                "image_urls": imgs,
                "color_attr_id": o.get("attr_id") or 0,
                "color_value": o.get("option_ru") or opt_zh,
                "color_dict_id": o.get("dict_value_id"),
            })
        currency = (getattr(ctx.settings, "price_currency", "RUB") or "RUB").upper()
        items = build_variant_items(title_ru, desc_ru, str(pid), desc_id, type_id,
                                    base_attrs, variants, currency, dims_arg,
                                    model_name=title_ru)
    else:
        items = build_import_payload(
            title_ru=title_ru, description_ru=desc_ru,
            offer_id=str(pid), price_rub=float(price or 0),
            category_id=desc_id, type_id=type_id,
            attributes=base_attrs, image_urls=gallery_urls,
            currency_code=(getattr(ctx.settings, "price_currency", "RUB") or "RUB").upper(),
            dims=dims_arg)["items"]

    result = await ctx.ozon.import_products(items)
    task_id = result.get("result", {}).get("task_id")
    conn.execute("INSERT INTO listings(product_id, import_task_id) VALUES(?,?)", (pid, str(task_id)))
    conn.commit()

    status_text, err, ozon_pid = "", "", ""
    for _ in range(12):
        await asyncio.sleep(5)
        info = await ctx.ozon.import_task_info(int(task_id))
        rows = info.get("result", {}).get("items", [])
        if rows:
            status_text = str(rows[0].get("status", ""))
            ozon_pid = str(rows[0].get("product_id", "") or "")
            if status_text == "failed":
                err = json.dumps(rows[0].get("errors", []), ensure_ascii=False)
                break
            if status_text in ("exported", "imported"):
                break
    conn.execute("UPDATE listings SET result_json=? WHERE product_id=?",
                 (json.dumps({"status": status_text, "error": err}, ensure_ascii=False), pid))
    final = "listed" if status_text in ("exported", "imported") else "failed"
    conn.execute("UPDATE products SET status=?, ozon_product_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 (final, ozon_pid or None, pid))
    conn.commit()
    # 发布成功后同步一次价格到 Ozon（import_payload 含价格，这里确保同步）
    if final == "listed" and price and price > 0:
        try:
            await ctx.ozon.update_price(int(pid), float(price))
        except Exception:  # noqa: BLE001, S110
            pass  # 价格同步失败不阻塞主流程，人审页可手动改价


def persist_raw_product(conn, rp) -> int:
    """落库已采集商品（collected）并排队 generate，返回 product_id。"""
    cur = conn.execute(
        "INSERT INTO products(source_url, platform, status) VALUES(?, '1688', 'collected')",
        (rp.source_url,))
    pid = cur.lastrowid
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(?,?)",
                 (pid, rp.model_dump_json()))
    for u in rp.main_images:
        conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(?,'main',?)", (pid, u))
    for u in rp.detail_images:
        conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(?,'detail',?)", (pid, u))
    conn.commit()
    enqueue(conn, "generate", {"product_id": pid})
    return pid


def collect_from_html(ctx, file_bytes: bytes, filename: str) -> int:
    from openoctopus.collector.html_parse import parse_product_html
    from openoctopus.db import get_conn

    rp = parse_product_html(file_bytes.decode("utf-8", "ignore"), f"upload:{filename}")
    conn = get_conn(ctx.db_path)
    return persist_raw_product(conn, rp)


async def handle_regenerate_image(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    img_id = payload["image_id"]
    img = conn.execute("SELECT * FROM images WHERE id=?", (img_id,)).fetchone()
    if img is None:
        return
    key_hint = f"products/{img['product_id']}/{img['kind']}-{img_id}"
    conn.execute("UPDATE images SET status='pending', translated_url=NULL, meta_json='{}' "
                 "WHERE id=?", (img_id,))
    conn.execute("UPDATE products SET status='generating' WHERE id=?", (img['product_id'],))
    conn.commit()
    try:
        url = await ctx.image_translator.translate(
            img["source_url"], key_hint,
            prompt_override=payload.get("prompt_override") or None)
    except Exception as e:  # noqa: BLE001
        conn.execute("UPDATE images SET status='failed', meta_json=? WHERE id=?",
                     (json.dumps({"error": str(e)[:200]}, ensure_ascii=False), img_id))
    else:
        conn.execute("UPDATE images SET translated_url=?, status='uploaded' WHERE id=?",
                     (url, img_id))
    conn.execute("UPDATE products SET status='review' WHERE id=?", (img['product_id'],))
    conn.commit()


HANDLERS = {"collect": handle_collect, "generate": handle_generate, "publish": handle_publish,
            "regenerate_image": handle_regenerate_image}
