import json as _json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from openoctopus import login as login_mod
from openoctopus.db import get_conn, init_db
from openoctopus.jobs.handlers import (
    HANDLERS,
    collect_from_html,
    persist_raw_product,
    upsert_translation,
)
from openoctopus.jobs.queue import JobRunner, enqueue

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATUS_GROUPS = [("new", "待处理"), ("collected", "已采集"), ("generating", "生成中"),
                 ("review", "待审"), ("publishing", "发布中"), ("listed", "已上架"),
                 ("failed", "失败")]


def create_app(ctx, run_worker: bool = True) -> FastAPI:
    init_db(ctx.db_path)
    conn = get_conn(ctx.db_path)
    # 认领僵尸任务：上次进程死时停在 running 的 job 永远不会被认领
    conn.execute("UPDATE jobs SET status='queued', error=NULL WHERE status='running'")
    conn.commit()
    app = FastAPI()
    runner = JobRunner(conn, HANDLERS, ctx)
    app.state.login_session = None
    app.state.login_info = {"status": "idle", "logged_in": False, "checked_at": None}

    @app.middleware("http")
    async def _cors_pna(request: Request, call_next):
        """允许 1688 页面跨域 POST 到本机：常规 CORS + Chrome 私网访问(PNA)头。"""
        if request.method == "OPTIONS":
            return Response(status_code=200, headers={
                "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Private-Network": "true",
                "Access-Control-Max-Age": "86400",
            })
        resp = await call_next(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    def _login_snapshot():
        info = dict(app.state.login_info)
        if info["status"] == "idle" and Path(ctx.settings.playwright_storage_state).exists():
            info["logged_in"] = True
        return info

    @app.on_event("startup")
    async def _start():
        if run_worker:
            import asyncio
            app.state.worker = asyncio.create_task(runner.run_forever())

    @app.on_event("shutdown")
    async def _stop():
        w = getattr(app.state, "worker", None)
        if w:
            w.cancel()
        for client in (
            getattr(getattr(ctx, "ozon", None), "http", None),
            getattr(getattr(ctx, "image_translator", None), "http", None),
            getattr(getattr(ctx, "content_translator", None), "client", None),
        ):
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001, S110
                    pass

    @app.get("/", response_class=HTMLResponse)
    def kanban(request: Request, status: str = "all", q: str = "", page: int = 1):
        conn = get_conn(ctx.db_path)
        statuses = {st: label for st, label in STATUS_GROUPS}
        if status not in statuses:
            status = "all"
        q = (q or "").strip()
        counts = {st: conn.execute("SELECT count(*) FROM products WHERE status=?",
                                    (st,)).fetchone()[0] for st in statuses}
        counts["all"] = sum(counts.values())
        where, params = [], []
        if status != "all":
            where.append("p.status=?")
            params.append(status)
        if q:
            where.append("(p.source_url LIKE ? OR EXISTS (SELECT 1 FROM translations t "
                         "WHERE t.product_id=p.id AND t.field='title' AND t.ru LIKE ?))")
            params += [f"%{q}%", f"%{q}%"]
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        per_page = 24
        total = conn.execute(f"SELECT count(*) FROM products p {where_sql}",
                             params).fetchone()[0]
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(max(1, page), pages)
        sql = ("SELECT p.id, p.source_url, p.status, p.price_rub, "
               "(SELECT t.ru FROM translations t WHERE t.product_id=p.id AND t.field='title' "
               " LIMIT 1) AS title_ru, "
               "(SELECT i.translated_url FROM images i WHERE i.product_id=p.id AND i.kind='main' "
               " AND i.translated_url IS NOT NULL ORDER BY i.id LIMIT 1) AS thumb "
               f"FROM products p {where_sql} ")
        sql += ("ORDER BY CASE p.status WHEN 'review' THEN 0 WHEN 'publishing' THEN 1 "
                "WHEN 'generating' THEN 2 WHEN 'collected' THEN 3 WHEN 'new' THEN 4 "
                "WHEN 'failed' THEN 5 ELSE 6 END, p.updated_at DESC LIMIT ? OFFSET ?")
        items = conn.execute(sql, [*params, per_page, (page - 1) * per_page]).fetchall()
        job_by_product = {}
        for j in conn.execute(
                "SELECT id, type, status, retries, error, payload_json FROM jobs "
                "WHERE status IN ('queued','running','failed') ORDER BY id DESC").fetchall():
            try:
                pid = _json.loads(j["payload_json"] or "{}").get("product_id")
            except _json.JSONDecodeError:
                continue
            if pid is not None and pid not in job_by_product:
                job_by_product[pid] = dict(j)
        return TEMPLATES.TemplateResponse(request, "kanban.html", {
            "items": items, "status": status, "counts": counts,
            "q": q, "page": page, "pages": pages, "total": total,
            "chips": [("all", "全部")] + STATUS_GROUPS, "login": _login_snapshot(),
            "jobs": job_by_product,
            "currency": (ctx.settings.price_currency or "RUB").upper()})

    @app.get("/login/status")
    def login_status():
        return JSONResponse(_login_snapshot())

    @app.post("/login/start")
    def login_start():
        session = login_mod.LoginSession(ctx.settings.playwright_storage_state)
        app.state.login_session = session
        session.start()
        app.state.login_info = {"status": "waiting", "logged_in": False, "checked_at": None}
        return RedirectResponse("/", status_code=303)

    @app.post("/login/finish")
    def login_finish():
        session = app.state.login_session
        if session is None or session.status != "waiting":
            return RedirectResponse("/", status_code=303)
        saved = session.finish()
        logged_in = saved and login_mod.verify_login(ctx.settings.playwright_storage_state)
        app.state.login_info = {"status": "done", "logged_in": logged_in,
                                "checked_at": datetime.now(timezone.utc).isoformat()}
        return RedirectResponse("/", status_code=303)

    @app.post("/products")
    def submit(url: str = Form(...)):
        """支持一次粘贴多行 1688 链接批量采集。"""
        from urllib.parse import urlsplit, urlunsplit

        conn = get_conn(ctx.db_path)
        n = 0
        for line in url.splitlines():
            line = line.strip()
            if not line or "1688.com" not in line:
                continue
            parts = urlsplit(line)
            if parts.scheme and parts.netloc:
                line = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            try:
                cur = conn.execute(
                    "INSERT INTO products(source_url, platform, status) "
                    "VALUES(?, '1688', 'new')", (line,))
            except Exception:  # noqa: BLE001, S112
                continue  # 重复链接跳过
            enqueue(conn, "collect", {"product_id": cur.lastrowid})
            n += 1
        conn.commit()
        return RedirectResponse("/", status_code=303)

    @app.post("/products/import-html")
    async def import_html(file: UploadFile):
        collect_from_html(ctx, await file.read(), file.filename)
        return RedirectResponse("/", status_code=303)

    @app.post("/products/import-json")
    async def import_json(request: Request):
        from openoctopus.models import RawProduct

        try:
            rp = RawProduct(**await request.json())
        except Exception:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": "invalid payload"}, status_code=400)
        conn = get_conn(ctx.db_path)
        pid = persist_raw_product(conn, rp)
        return JSONResponse({"ok": True, "product_id": pid})

    @app.get("/media/proxy")
    async def media_proxy(u: str = ""):
        """代理外部图片（1688 CDN 有防盗链，浏览器直连会 403）。"""
        from urllib.parse import urlparse

        p = urlparse(u)
        if p.scheme not in ("http", "https") or not p.netloc:
            return Response("bad url", status_code=400)
        import httpx

        headers = {
            "Referer": "https://detail.1688.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        }
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(u, headers=headers)
                r.raise_for_status()
        except Exception:  # noqa: BLE001
            return Response("fetch failed", status_code=502)
        return Response(r.content, media_type=r.headers.get("content-type", "image/jpeg"),
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/products/{pid}", response_class=HTMLResponse)
    def review(request: Request, pid: int):
        conn = get_conn(ctx.db_path)
        row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Product not found")
        p = dict(row)
        t = {r["field"]: dict(r) for r in conn.execute(
            "SELECT field, zh, ru FROM translations WHERE product_id=?", (pid,))}
        images = conn.execute("SELECT * FROM images WHERE product_id=? ORDER BY kind, id",
                              (pid,)).fetchall()
        mapping = conn.execute("SELECT * FROM category_mappings WHERE product_id=?", (pid,)).fetchone()
        cats = conn.execute("SELECT id, title FROM ozon_categories WHERE id LIKE '%:%' "
                              "ORDER BY title LIMIT 500").fetchall()
        from openoctopus.content.titles import check_title, style_label
        from openoctopus.listing.enrich import parse_rich_content
        from openoctopus.listing.preflight import preflight
        from openoctopus.listing.pricing import margin_pct, price_advice
        from openoctopus.rates import get_rate

        variants = []
        cost_cny = 0.0
        rate = ctx.settings.price_cny_to_rub
        snap = conn.execute("SELECT raw_json FROM source_snapshots WHERE product_id=? "
                            "ORDER BY id DESC", (pid,)).fetchone()
        if snap:
            from openoctopus.models import RawProduct, variant_dim_index

            rraw = RawProduct(**_json.loads(snap["raw_json"]))
            cost_cny = float(rraw.price_cny or 0)
            if not t.get("title", {}).get("zh"):
                t.setdefault("title", {})["zh"] = rraw.title_zh
            if not t.get("description", {}).get("zh"):
                t.setdefault("description", {})["zh"] = rraw.description_zh
            if rraw.skus:
                dimn = list(rraw.skus[0].props.keys())[variant_dim_index(rraw)]
                groups: dict[str, list] = {}
                for s in rraw.skus:
                    if dimn in s.props:
                        groups.setdefault(s.props[dimn], []).append(s)
                omap = {r["option_zh"]: dict(r) for r in conn.execute(
                    "SELECT * FROM sku_options WHERE product_id=?", (pid,))}
                swatches = {r["label"]: (r["translated_url"] or r["source_url"])
                            for r in conn.execute(
                                "SELECT label, translated_url, source_url FROM images "
                                "WHERE product_id=? AND kind='swatch'", (pid,))}
                rate = get_rate(conn, ctx.settings.price_cny_to_rub)
                for opt, grp in sorted(groups.items()):
                    cny = min((g.price_cny for g in grp if g.price_cny), default=0) or rraw.price_cny
                    o = omap.get(opt, {})
                    variants.append({"zh": opt, "ru": o.get("option_ru", ""),
                                     "price_rub": round(cny * rate), "combos": len(grp),
                                     "matched": bool(o.get("dict_value_id")),
                                     "swatch": swatches.get(opt, "")})
        hero = next((r["translated_url"] for r in images
                     if r["kind"] == "main" and r["translated_url"]), None)

        rich_blocks = parse_rich_content(p.get("rich_content") or "")
        title_candidates = conn.execute(
            "SELECT id, style, ru FROM title_candidates WHERE product_id=? ORDER BY id",
            (pid,)).fetchall()
        title_warnings = check_title(t.get("title", {}).get("ru", ""))
        keywords: list = []
        if p.get("keywords"):
            try:
                keywords = _json.loads(p["keywords"])
            except _json.JSONDecodeError:
                keywords = []
        advice = price_advice(cost_cny, commission_pct=ctx.settings.ozon_commission_pct,
                              shipping_cny=ctx.settings.shipping_cny,
                              target_margin_pct=ctx.settings.target_margin_pct, rate=rate)
        cur_price = float(p.get("price_rub") or 0)
        cur_margin = margin_pct(cur_price, advice)
        dims_count = sum(1 for k in ("length_mm", "width_mm", "height_mm", "weight_g")
                         if p.get(k))
        rus = [v["ru"] for v in variants if v["ru"]]
        checks = preflight(mapping=mapping, images=images, title_warnings=title_warnings,
                           price=cur_price, advice=advice,
                           last_price_sent=p.get("last_price_sent"),
                           stock=p.get("stock"), dims_count=dims_count,
                           unmatched_colors=sum(1 for v in variants if not v["matched"]),
                           dup_colors=len(rus) != len(set(rus)))
        content_job_types = [
            r["type"] for r in conn.execute(
                "SELECT DISTINCT type FROM jobs WHERE status IN ('queued','running') "
                "AND type IN ('regenerate_video','regenerate_rich','regenerate_titles',"
                "'fetch_keywords','make_infographic','improve_description') "
                "AND json_extract(payload_json, '$.product_id') = ?", (pid,)).fetchall()]
        content_jobs = len(content_job_types)
        return TEMPLATES.TemplateResponse(request, "review.html",
                                          {"p": p, "t": t, "images": images, "hero": hero,
                                           "mapping": mapping, "cats": cats, "variants": variants,
                                           "rich_blocks": rich_blocks,
                                           "title_candidates": title_candidates,
                                           "title_warnings": title_warnings,
                                           "keywords": keywords,
                                           "advice": advice, "cur_margin": cur_margin,
                                           "checks": checks, "rate": rate,
                                           "style_label": style_label,
                                           "r2_base": ctx.settings.r2_public_base_url or "",
                                           "content_jobs": content_jobs,
                                           "content_job_types": content_job_types,
                                           "currency": (ctx.settings.price_currency or "RUB").upper()})

    @app.post("/products/{pid}/edit")
    async def edit(request: Request, pid: int, title_ru: str = Form(""),
                   description_ru: str = Form(""),
                   price_rub: str = Form(""), stock: str = Form("0"),
                   ozon_category_id: str = Form(...),
                   attributes_json: str = Form("{}"), length_mm: str = Form(""),
                   width_mm: str = Form(""), height_mm: str = Form(""),
                   weight_g: str = Form(""), rich_content: str = Form("")):
        try:
            attrs = _json.loads(attributes_json)
        except _json.JSONDecodeError:
            return HTMLResponse("Invalid attributes_json", status_code=400)
        # 类目字段为 "description_category_id:type_id" 复合 key；纯数字视为只有类目
        raw_cat = (ozon_category_id or "").strip()
        if ":" in raw_cat:
            desc_id, type_id = raw_cat.split(":", 1)
        else:
            desc_id, type_id = raw_cat, ""
        form = await request.form()
        selected_ids = {k[4:] for k in form if k.startswith("sel_")}
        conn = get_conn(ctx.db_path)
        conn.execute("UPDATE images SET selected=0 WHERE product_id=?", (pid,))
        for sid in selected_ids:
            if sid.isdigit():
                conn.execute("UPDATE images SET selected=1 WHERE id=? AND product_id=?",
                             (int(sid), pid))
        if price_rub != "":
            try:
                price_rub_val = float(price_rub)
            except ValueError:
                return HTMLResponse("Invalid price_rub", status_code=400)
        else:
            price_rub_val = None
        if not title_ru.strip():
            pick = str(form.get("title_pick") or "")
            if pick.isdigit():
                row = conn.execute(
                    "SELECT ru FROM title_candidates WHERE id=? AND product_id=?",
                    (int(pick), pid)).fetchone()
                if row:
                    title_ru = row["ru"]
        upsert_translation(conn, pid, "title", "", title_ru)
        upsert_translation(conn, pid, "description", "", description_ru)
        if price_rub_val is not None:
            conn.execute("UPDATE products SET price_rub=? WHERE id=?", (price_rub_val, pid))
        try:
            stock_val = int(stock) if stock.strip() else 0
        except ValueError:
            stock_val = 0
        conn.execute("UPDATE products SET stock=? WHERE id=?", (stock_val, pid))
        rc_raw = str(form.get("rc_raw_mode") or "")
        rc_count = str(form.get("rc_count") or "")
        if rc_raw == "1" or (not rc_count and rich_content.strip()):
            if rich_content.strip():
                try:
                    _json.loads(rich_content)
                except _json.JSONDecodeError:
                    return HTMLResponse("Invalid rich_content JSON", status_code=400)
                conn.execute("UPDATE products SET rich_content=? WHERE id=?",
                             (rich_content.strip(), pid))
        elif rc_count.isdigit() and int(rc_count) > 0:
            from openoctopus.listing.enrich import build_rich_content_from_blocks

            blocks = [{"img": form.get(f"rc_img_{i}", ""),
                       "title": form.get(f"rc_title_{i}", ""),
                       "text": form.get(f"rc_text_{i}", "")}
                      for i in range(int(rc_count))]
            rich = build_rich_content_from_blocks(blocks)
            if rich:
                conn.execute("UPDATE products SET rich_content=? WHERE id=?", (rich, pid))
        dims = {}
        for field, key in (("length_mm", length_mm), ("width_mm", width_mm),
                           ("height_mm", height_mm), ("weight_g", weight_g)):
            if (val := (key or "").strip()):
                try:
                    dims[field] = float(val)
                except ValueError:
                    return HTMLResponse(f"Invalid {field}", status_code=400)
        if dims:
            conn.execute(
                "UPDATE products SET {} WHERE id=?".format(
                    ", ".join(f"{k}=?" for k in dims)),
                (*dims.values(), pid))
        conn.execute(
            "INSERT INTO category_mappings(product_id, ozon_category_id, type_id, "
            "attributes_json, human_confirmed)"
            " VALUES(?,?,?,?,1) ON CONFLICT(product_id) DO UPDATE SET "
            "ozon_category_id=excluded.ozon_category_id, type_id=excluded.type_id, "
            "attributes_json=excluded.attributes_json,"
            " human_confirmed=1", (pid, desc_id, type_id, _json.dumps(attrs, ensure_ascii=False)))
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/approve")
    def approve(pid: int):
        conn = get_conn(ctx.db_path)
        row = conn.execute("SELECT status FROM products WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Product not found")
        if row["status"] not in ("review", "collected", "generating", "failed", "listed"):
            return HTMLResponse(
                "Approve only allowed in review/collected/generating/failed/listed status",
                status_code=400)
        conn.execute("UPDATE products SET status='publishing' WHERE id=?", (pid,))
        conn.commit()
        enqueue(conn, "publish", {"product_id": pid})
        return RedirectResponse("/", status_code=303)

    @app.post("/products/{pid}/regenerate")
    def regenerate(pid: int):
        conn = get_conn(ctx.db_path)
        row = conn.execute("SELECT status FROM products WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Product not found")
        if row["status"] not in ("review", "collected", "generating", "failed"):
            return HTMLResponse(
                "Regenerate only allowed in review/collected/generating/failed status",
                status_code=400)
        conn.execute("UPDATE products SET status='generating' WHERE id=?", (pid,))
        conn.commit()
        enqueue(conn, "generate", {"product_id": pid})
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/images/{imgid}/regenerate")
    def regenerate_image(pid: int, imgid: int, prompt_override: str = Form("")):
        conn = get_conn(ctx.db_path)
        img = conn.execute("SELECT * FROM images WHERE id=? AND product_id=?",
                           (imgid, pid)).fetchone()
        if img is None:
            raise HTTPException(status_code=404, detail="Image not found")
        enqueue(conn, "regenerate_image", {"product_id": pid, "image_id": imgid,
                                            "prompt_override": prompt_override.strip()})
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/keywords/fetch")
    def fetch_keywords(pid: int):
        conn = get_conn(ctx.db_path)
        if conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Product not found")
        enqueue(conn, "fetch_keywords", {"product_id": pid})
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/titles/regenerate")
    def regenerate_titles(pid: int):
        conn = get_conn(ctx.db_path)
        if conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Product not found")
        enqueue(conn, "regenerate_titles", {"product_id": pid})
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/content/video/regenerate")
    def regenerate_video(pid: int):
        conn = get_conn(ctx.db_path)
        if conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Product not found")
        enqueue(conn, "regenerate_video", {"product_id": pid})
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/content/rich/regenerate")
    def regenerate_rich(pid: int):
        conn = get_conn(ctx.db_path)
        if conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Product not found")
        enqueue(conn, "regenerate_rich", {"product_id": pid})
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/infographic")
    def make_infographic_route(pid: int):
        conn = get_conn(ctx.db_path)
        if conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Product not found")
        enqueue(conn, "make_infographic", {"product_id": pid})
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/description/improve")
    def improve_description_route(pid: int):
        conn = get_conn(ctx.db_path)
        if conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Product not found")
        enqueue(conn, "improve_description", {"product_id": pid})
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/publish-batch")
    async def publish_batch(request: Request):
        form = await request.form()
        conn = get_conn(ctx.db_path)
        n = 0
        for pid in form.getlist("pid"):
            if not str(pid).isdigit():
                continue
            row = conn.execute("SELECT status FROM products WHERE id=?", (int(pid),)).fetchone()
            if row is None:
                continue
            conn.execute("UPDATE products SET status='publishing' WHERE id=?", (int(pid),))
            enqueue(conn, "publish", {"product_id": int(pid)})
            n += 1
        conn.commit()
        return RedirectResponse("/", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        conn = get_conn(ctx.db_path)
        rows = conn.execute(
            "SELECT m.product_id, p.status, p.source_url, p.last_price_sent, "
            "(SELECT t.ru FROM translations t WHERE t.product_id=m.product_id "
            " AND t.field='title' LIMIT 1) AS title_ru, "
            "COUNT(*) AS skus, MIN(m.rating) AS rating_min, MAX(m.rating) AS rating_max, "
            "SUM(m.stock) AS stock_total, "
            "SUM(CASE WHEN m.availability='AVAILABLE' THEN 1 ELSE 0 END) AS available_n, "
            "GROUP_CONCAT(DISTINCT CASE WHEN m.reason != '' THEN m.reason END) AS reasons, "
            "MAX(m.refreshed_at) AS refreshed_at "
            "FROM metrics m LEFT JOIN products p ON p.id=m.product_id "
            "GROUP BY m.product_id ORDER BY rating_min ASC, m.product_id").fetchall()
        summary = conn.execute(
            "SELECT COUNT(DISTINCT product_id) AS n, COUNT(*) AS skus, "
            "AVG(rating) AS avg_rating, SUM(stock) AS stock_total FROM metrics").fetchone()
        return TEMPLATES.TemplateResponse(request, "dashboard.html", {
            "rows": rows, "summary": summary, "currency":
            (ctx.settings.price_currency or "RUB").upper()})

    @app.get("/promotions", response_class=HTMLResponse)
    def promotions(request: Request):
        conn = get_conn(ctx.db_path)
        rows = []
        for p_ in conn.execute("SELECT * FROM promotions ORDER BY date_end"):
            n = conn.execute("SELECT count(*) FROM promotion_candidates WHERE action_id=?",
                             (p_["action_id"],)).fetchone()[0]
            rows.append({**dict(p_), "candidates": n})
        return TEMPLATES.TemplateResponse(request, "promotions.html", {"rows": rows})

    @app.post("/promotions/refresh")
    def promotions_refresh():
        conn = get_conn(ctx.db_path)
        enqueue(conn, "refresh_promotions", {})
        conn.commit()
        return RedirectResponse("/promotions", status_code=303)

    @app.get("/promotions/{action_id}", response_class=HTMLResponse)
    def promotion_detail(request: Request, action_id: int):
        from openoctopus.listing.pricing import price_advice

        conn = get_conn(ctx.db_path)
        promo = conn.execute("SELECT * FROM promotions WHERE action_id=?",
                             (action_id,)).fetchone()
        if promo is None:
            raise HTTPException(status_code=404, detail="Promotion not found")
        pid_map: dict[str, int] = {}
        for r in conn.execute("SELECT product_id, result_json FROM listings ORDER BY id"):
            try:
                for it in (_json.loads(r["result_json"] or "{}").get("items") or []):
                    if it.get("product_id"):
                        pid_map.setdefault(str(it["product_id"]), r["product_id"])
            except _json.JSONDecodeError:
                continue
        for r in conn.execute("SELECT id, ozon_product_id FROM products "
                              "WHERE ozon_product_id IS NOT NULL"):
            pid_map.setdefault(str(r["ozon_product_id"]), r["id"])
        costs: dict[int, float] = {}
        for r in conn.execute("SELECT p.id AS pid, s.raw_json FROM products p "
                              "JOIN source_snapshots s ON s.product_id = p.id"):
            try:
                cny = float(_json.loads(r["raw_json"]).get("price_cny") or 0)
            except (ValueError, _json.JSONDecodeError):
                cny = 0
            costs[r["pid"]] = max(costs.get(r["pid"], 0.0), cny)
        titles: dict[int, str] = {}
        for r in conn.execute("SELECT product_id, ru FROM translations "
                              "WHERE field='title'"):
            titles[r["product_id"]] = r["ru"]
        rows = []
        for c in conn.execute("SELECT * FROM promotion_candidates WHERE action_id=? "
                              "ORDER BY participating DESC, max_action_price DESC, product_id",
                              (action_id,)):
            local = pid_map.get(str(c["product_id"]))
            be = None
            if local and costs.get(local):
                be = price_advice(
                    costs[local], commission_pct=ctx.settings.ozon_commission_pct,
                    shipping_cny=ctx.settings.shipping_cny,
                    target_margin_pct=ctx.settings.target_margin_pct)["break_even_cny"]
            rows.append({**dict(c), "local_id": local, "title_ru": titles.get(local, ""),
                         "break_even": be,
                         "ok": be is None or float(c["max_action_price"] or 0) >= be})
        return TEMPLATES.TemplateResponse(request, "promotion_detail.html",
                                          {"promo": dict(promo), "rows": rows})

    @app.post("/promotions/{action_id}/activate")
    async def promotion_activate(request: Request, action_id: int):
        form = await request.form()
        products = []
        for key in form:
            if not key.startswith("sel_") or not key[4:].isdigit():
                continue
            pid = key[4:]
            try:
                price = float(str(form.get(f"price_{pid}") or "").strip())
            except ValueError:
                continue
            products.append({"product_id": int(pid), "action_price": round(price, 2)})
        if products:
            conn = get_conn(ctx.db_path)
            enqueue(conn, "promotion_activate",
                    {"action_id": action_id, "products": products})
            conn.commit()
        return RedirectResponse(f"/promotions/{action_id}", status_code=303)

    @app.post("/promotions/{action_id}/deactivate")
    async def promotion_deactivate(request: Request, action_id: int):
        form = await request.form()
        ids = [int(k[4:]) for k in form if k.startswith("sel_") and k[4:].isdigit()]
        if ids:
            conn = get_conn(ctx.db_path)
            enqueue(conn, "promotion_deactivate",
                    {"action_id": action_id, "product_ids": ids})
            conn.commit()
        return RedirectResponse(f"/promotions/{action_id}", status_code=303)

    @app.post("/dashboard/refresh")
    def dashboard_refresh():
        conn = get_conn(ctx.db_path)
        enqueue(conn, "refresh_metrics", {})
        conn.commit()
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs_page(request: Request):
        conn = get_conn(ctx.db_path)
        rows = []
        for j in conn.execute(
                "SELECT id, type, status, retries, error, created_at, payload_json FROM jobs "
                "ORDER BY id DESC LIMIT 100").fetchall():
            try:
                pid = _json.loads(j["payload_json"] or "{}").get("product_id")
            except _json.JSONDecodeError:
                pid = None
            rows.append({**dict(j), "product_id": pid})
        log_tail = "(日志不可读)"
        try:
            with open(ctx.settings.log_path, errors="replace") as f:
                log_tail = "".join(f.readlines()[-120:]) or "(空)"
        except OSError:
            pass
        return TEMPLATES.TemplateResponse(request, "jobs.html",
                                          {"jobs": rows, "log_tail": log_tail})

    @app.post("/jobs/{jid}/retry")
    def retry(jid: int):
        conn = get_conn(ctx.db_path)
        conn.execute("UPDATE jobs SET status='queued', error=NULL WHERE id=?", (jid,))
        conn.commit()
        return RedirectResponse("/", status_code=303)

    @app.post("/products/{pid}/delete")
    def delete_product(pid: int):
        conn = get_conn(ctx.db_path)
        for t in ("listings", "translations", "images", "category_mappings", "source_snapshots"):
            conn.execute(f"DELETE FROM {t} WHERE product_id=?", (pid,))
        conn.execute("DELETE FROM jobs WHERE payload_json LIKE ?",
                     (f'%"product_id": {pid}%',))
        conn.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
        return RedirectResponse("/", status_code=303)

    return app
