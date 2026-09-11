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

    # 标题工程：生成结构化候选，默认采用第一个（人审页可切换候选）
    if getattr(ctx.settings, "ozon_scrape_proxy", ""):
        try:
            await _fetch_keywords(ctx, conn, pid, query_ru=tc.title_ru)
        except Exception:  # noqa: BLE001, S110
            pass
    try:
        cands = await _generate_title_candidates(
            ctx, conn, pid, title_zh=raw.title_zh,
            title_ru=tc.title_ru, desc_ru=tc.description_ru)
        if cands:
            upsert_translation(conn, pid, "title", raw.title_zh, cands[0]["text"])
            conn.commit()
    except Exception:  # noqa: BLE001, S110
        pass

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
    # 视频 + 富内容（人审页可预览/编辑；发布时复用）
    try:
        _content_assets(ctx, conn, pid, title_ru=tc.title_ru, desc_ru=tc.description_ru,
                        gallery_urls=_gallery_urls(conn, pid), title_zh=raw.title_zh)
    except Exception:  # noqa: BLE001, S110
        pass
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
    color_attrs = [a for a in attrs_schema
                   if "цвет" in str(a.get("name", "")).lower()]
    color_attr = (next((a for a in color_attrs if int(a.get("dictionary_id") or 0) > 0), None)
                  or (color_attrs[0] if color_attrs else None))
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


def _save_title_candidates(conn, pid: int, cands: list[dict]) -> None:
    conn.execute("DELETE FROM title_candidates WHERE product_id=?", (pid,))
    for c in cands:
        conn.execute("INSERT INTO title_candidates(product_id, style, ru) VALUES(?,?,?)",
                     (pid, c.get("style") or "", (c.get("text") or "").strip()[:200]))
    conn.commit()


async def _generate_title_candidates(ctx, conn, pid: int, *, title_zh: str,
                                     title_ru: str, desc_ru: str) -> list[dict]:
    """生成候选标题并落库；LLM 失败时模板兜底。"""
    from openoctopus.content.titles import (
        compat_ru,
        generate_titles,
        material_ru,
        template_titles,
    )

    keywords: list[str] = []
    row = conn.execute("SELECT keywords FROM products WHERE id=?", (pid,)).fetchone()
    if row and row["keywords"]:
        try:
            keywords = json.loads(row["keywords"])
        except json.JSONDecodeError:
            keywords = []
    compat = compat_ru(title_zh)
    try:
        cands = await generate_titles(
            ctx.llm_client, ctx.settings.content_model,
            title_zh=title_zh, title_ru=title_ru, desc_ru=desc_ru,
            compat=compat, type_ru="ремешок для умных часов" if compat else "",
            keywords=keywords)
    except Exception:  # noqa: BLE001
        cands = template_titles(
            type_ru="Ремешок для умных часов" if compat else "Ремешок",
            material=material_ru(title_zh), compat=compat)
    _save_title_candidates(conn, pid, cands)
    return cands


async def _fetch_keywords(ctx, conn, pid: int, *, query_ru: str) -> list[str]:
    """抓 Ozon 搜索词并落库；任何失败返回 []（不影响主流程）。"""
    from openoctopus.content.keywords import extract_keywords, fetch_ozon_titles

    q = (query_ru or "").split(",")[0].strip()[:60]
    if not q:
        return []
    proxy = getattr(ctx.settings, "ozon_scrape_proxy", "") or ""
    titles = await fetch_ozon_titles(q, proxy=proxy)
    if not titles:
        return []
    keywords = await extract_keywords(ctx.llm_client, ctx.settings.content_model, titles)
    if keywords:
        conn.execute("UPDATE products SET keywords=? WHERE id=?",
                     (json.dumps(keywords, ensure_ascii=False), pid))
        conn.commit()
    return keywords


def _material(title_zh: str) -> str:
    return ("textile" if any(w in (title_zh or "")
                             for w in ("尼龙", "尼龍", "编织", "編織")) else "silicone")


def _gallery_urls(conn, pid: int) -> list[str]:
    return list(dict.fromkeys(
        r["translated_url"] or r["source_url"] for r in conn.execute(
            "SELECT translated_url, source_url FROM images WHERE product_id=? "
            "AND kind='main' AND selected=1 AND status='uploaded' ORDER BY id", (pid,))))


def _content_assets(ctx, conn, pid: int, *, title_ru: str, desc_ru: str,
                    gallery_urls: list[str], title_zh: str,
                    force_video: bool = False, force_rich: bool = False) -> tuple[str, str]:
    """返回 (video_url, rich_content)。优先复用已存库版本，缺失则生成并落库。"""
    from openoctopus.listing.enrich import build_rich_content

    row = conn.execute("SELECT video_url, rich_content FROM products WHERE id=?",
                       (pid,)).fetchone()
    video_url = "" if force_video else ((row["video_url"] or "") if row else "")
    rich = "" if force_rich else ((row["rich_content"] or "") if row else "")
    hint = "Нейлон" if _material(title_zh) == "textile" else "Силикон"
    if not rich and gallery_urls:
        try:
            rich = build_rich_content(title_ru, desc_ru, gallery_urls, material_hint=hint)
        except Exception:  # noqa: BLE001
            rich = ""
    if not video_url and ctx.storage and gallery_urls:
        key = f"products/{pid}/video.mp4"
        try:
            if (not force_video and callable(getattr(ctx.storage, "exists", None))
                    and ctx.storage.exists(key)):
                video_url = f"{ctx.storage.public_base}/{key}"
            else:
                from openoctopus.image.video import make_slideshow

                data = make_slideshow(gallery_urls,
                                      prefer_host=getattr(ctx.storage, "public_base", ""))
                if data:
                    video_url = ctx.storage.put(key, data, mime="video/mp4")
        except Exception:  # noqa: BLE001
            video_url = ""
    if rich or video_url:
        conn.execute("UPDATE products SET video_url=?, rich_content=? WHERE id=?",
                     (video_url, rich, pid))
        conn.commit()
    return video_url, rich


def _enrich_items(ctx, items: list[dict], *, pid: int, title_ru: str, desc_ru: str,
                  gallery_urls: list[str], dims_arg: dict | None, title_zh: str) -> None:
    """补充属性：注释、材质/尺寸、视频链接、Rich-контент（就地修改 items）。"""
    try:
        from openoctopus.db import get_conn
        from openoctopus.listing.enrich import build_extra_attributes, safe_hashtags

        conn = get_conn(ctx.db_path)
        video_url, rich = _content_assets(
            ctx, conn, pid, title_ru=title_ru, desc_ru=desc_ru,
            gallery_urls=gallery_urls, title_zh=title_zh)
        material = _material(title_zh)
        tags = safe_hashtags("ремешок", "умныечасы", "аксессуар",
                             "нейлон" if material == "textile" else "силикон")
        dims = dims_arg or {}
        extra = build_extra_attributes(
            description_ru=desc_ru, title_ru=title_ru,
            weight_g=dims.get("weight"), length_mm=dims.get("length"),
            width_mm=dims.get("width"), height_mm=dims.get("height"),
            material=material, video_url=video_url, rich_content=rich, hashtags=tags)
    except Exception:  # noqa: BLE001
        return
    for it in items:
        have = {a.get("id") for a in it.get("attributes", [])}
        it.setdefault("attributes", []).extend(a for a in extra if a["id"] not in have)


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
    prod_row = conn.execute("SELECT length_mm, width_mm, height_mm, weight_g, offer_id_prefix "
                            "FROM products WHERE id=?", (pid,)).fetchone()
    if prod_row:
        dims = {k: prod_row[k] for k in ("length_mm", "width_mm", "height_mm", "weight_g")
                if prod_row[k]}
    dims_arg = {"length": dims["length_mm"], "width": dims["width_mm"],
                "height": dims["height_mm"], "weight": dims["weight_g"]} if len(dims) == 4 else None
    price = conn.execute("SELECT price_rub FROM products WHERE id=?", (pid,)).fetchone()["price_rub"]
    stock = conn.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()["stock"] or 0

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
    prefix = (dict(prod_row).get("offer_id_prefix") or "").strip() if prod_row else ""
    base_offer = f"{prefix}{pid}" if prefix else str(pid)
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
        user_price = float(price) if price else 0
        for opt_zh, group in groups.items():
            o = opt_map.get(opt_zh, {})
            if user_price > 0:
                vprice = round(user_price, 2)
            else:
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
        items = build_variant_items(title_ru, desc_ru, base_offer, desc_id, type_id,
                                    base_attrs, variants, currency, dims_arg,
                                    model_name=title_ru)
    else:
        items = build_import_payload(
            title_ru=title_ru, description_ru=desc_ru,
            offer_id=base_offer, price_rub=float(price or 0),
            category_id=desc_id, type_id=type_id,
            attributes=base_attrs, image_urls=gallery_urls,
            currency_code=(getattr(ctx.settings, "price_currency", "RUB") or "RUB").upper(),
            dims=dims_arg)["items"]

    _enrich_items(ctx, items, pid=pid, title_ru=title_ru, desc_ru=desc_ru,
                  gallery_urls=gallery_urls, dims_arg=dims_arg,
                  title_zh=(raw_pub.title_zh if raw_pub else ""))

    result = await ctx.ozon.import_products(items)
    task_id = result.get("result", {}).get("task_id")
    conn.execute("INSERT INTO listings(product_id, import_task_id) VALUES(?,?)", (pid, str(task_id)))
    conn.commit()

    status_text, err, ozon_pid = "", "", ""
    TERMINAL = ("exported", "imported", "failed", "skipped")
    item_summary = []
    for _ in range(12):
        await asyncio.sleep(5)
        info = await ctx.ozon.import_task_info(int(task_id))
        rows = info.get("result", {}).get("items", [])
        if rows and all(str(r.get("status", "")) in TERMINAL for r in rows):
            item_summary = [{"offer_id": r.get("offer_id"), "status": r.get("status"),
                             "product_id": r.get("product_id")} for r in rows]
            failed = [r for r in rows if r.get("status") == "failed"]
            if failed:
                status_text = "failed"
                errs = []
                for r in failed:
                    errs.extend(r.get("errors", []))
                err = json.dumps(errs, ensure_ascii=False)
                ozon_pid = str(failed[0].get("product_id", "") or "")
            else:
                exported = [r for r in rows if r.get("status") in ("exported", "imported")]
                status_text = "imported" if exported else "skipped"
                ozon_pid = str((exported[0] if exported else rows[0]).get("product_id", "") or "")
            break
    conn.execute("UPDATE listings SET result_json=? WHERE product_id=?",
                 (json.dumps({"status": status_text, "error": err,
                              "items": item_summary}, ensure_ascii=False), pid))
    final = "listed" if status_text in ("exported", "imported", "skipped") else "failed"
    conn.execute("UPDATE products SET status=?, ozon_product_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 (final, ozon_pid or None, pid))
    conn.commit()
    # 发布成功后同步一次价格到 Ozon（注意用 Ozon 的 product_id，不是本地 id）
    if final == "listed" and price and price > 0 and ozon_pid:
        try:
            await ctx.ozon.update_price(int(ozon_pid), float(price))
        except Exception:  # noqa: BLE001, S110
            pass  # 价格同步失败不阻塞主流程，人审页可手动改价
    # 同步库存到 Ozon（Cel Small 仓库，cross-border 专用）
    if final == "listed" and stock > 0 and item_summary:
        WH_ID = 1020000812944000
        stocks_payload = []
        for it in item_summary:
            if it.get("status") in ("imported", "exported") and it.get("product_id"):
                stocks_payload.append({
                    "offer_id": it["offer_id"],
                    "product_id": it["product_id"],
                    "stock": stock,
                    "warehouse_id": WH_ID,
                })
        if stocks_payload:
            try:
                await ctx.ozon.set_stocks(stocks_payload)
            except Exception:  # noqa: BLE001, S110
                pass


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


def _regen_context(conn, pid: int) -> dict:
    t = {r["field"]: r["ru"] for r in conn.execute(
        "SELECT field, ru FROM translations WHERE product_id=?", (pid,))}
    title_zh = ""
    snap = conn.execute("SELECT raw_json FROM source_snapshots WHERE product_id=? "
                        "ORDER BY id DESC", (pid,)).fetchone()
    if snap:
        try:
            title_zh = json.loads(snap["raw_json"]).get("title_zh", "")
        except Exception:  # noqa: BLE001
            title_zh = ""
    return {"title_ru": t.get("title", ""), "desc_ru": t.get("description", ""),
            "title_zh": title_zh}


async def handle_regenerate_video(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    pid = payload["product_id"]
    info = _regen_context(conn, pid)
    _content_assets(ctx, conn, pid, title_ru=info["title_ru"], desc_ru=info["desc_ru"],
                    gallery_urls=_gallery_urls(conn, pid), title_zh=info["title_zh"],
                    force_video=True)


async def handle_regenerate_rich(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    pid = payload["product_id"]
    info = _regen_context(conn, pid)
    _content_assets(ctx, conn, pid, title_ru=info["title_ru"], desc_ru=info["desc_ru"],
                    gallery_urls=_gallery_urls(conn, pid), title_zh=info["title_zh"],
                    force_rich=True)


async def handle_regenerate_titles(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    pid = payload["product_id"]
    info = _regen_context(conn, pid)
    await _generate_title_candidates(ctx, conn, pid, title_zh=info["title_zh"],
                                     title_ru=info["title_ru"], desc_ru=info["desc_ru"])


async def handle_fetch_keywords(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    pid = payload["product_id"]
    info = _regen_context(conn, pid)
    await _fetch_keywords(ctx, conn, pid, query_ru=info["title_ru"])
    await _generate_title_candidates(ctx, conn, pid, title_zh=info["title_zh"],
                                     title_ru=info["title_ru"], desc_ru=info["desc_ru"])


HANDLERS = {"collect": handle_collect, "generate": handle_generate, "publish": handle_publish,
            "regenerate_image": handle_regenerate_image,
            "regenerate_video": handle_regenerate_video,
            "regenerate_rich": handle_regenerate_rich,
            "regenerate_titles": handle_regenerate_titles,
            "fetch_keywords": handle_fetch_keywords}
