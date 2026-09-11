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
    def kanban(request: Request, status: str = "all"):
        conn = get_conn(ctx.db_path)
        statuses = {st: label for st, label in STATUS_GROUPS}
        if status not in statuses:
            status = "all"
        counts = {st: conn.execute("SELECT count(*) FROM products WHERE status=?",
                                    (st,)).fetchone()[0] for st in statuses}
        counts["all"] = sum(counts.values())
        sql = ("SELECT p.id, p.source_url, p.status, p.price_rub, "
               "(SELECT t.ru FROM translations t WHERE t.product_id=p.id AND t.field='title' "
               " LIMIT 1) AS title_ru, "
               "(SELECT i.translated_url FROM images i WHERE i.product_id=p.id AND i.kind='main' "
               " AND i.translated_url IS NOT NULL ORDER BY i.id LIMIT 1) AS thumb "
               "FROM products p ")
        params: tuple = ()
        if status != "all":
            sql += "WHERE p.status=? "
            params = (status,)
        sql += ("ORDER BY CASE p.status WHEN 'review' THEN 0 WHEN 'publishing' THEN 1 "
                "WHEN 'generating' THEN 2 WHEN 'collected' THEN 3 WHEN 'new' THEN 4 "
                "WHEN 'failed' THEN 5 ELSE 6 END, p.updated_at DESC")
        items = conn.execute(sql, params).fetchall()
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
        from urllib.parse import urlsplit, urlunsplit

        url = url.strip()
        parts = urlsplit(url)
        if parts.scheme and parts.netloc:
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        conn = get_conn(ctx.db_path)
        cur = conn.execute(
            "INSERT INTO products(source_url, platform, status) VALUES(?, '1688', 'new')", (url,))
        conn.commit()
        enqueue(conn, "collect", {"product_id": cur.lastrowid})
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
        variants = []
        snap = conn.execute("SELECT raw_json FROM source_snapshots WHERE product_id=? "
                            "ORDER BY id DESC", (pid,)).fetchone()
        if snap:
            from openoctopus.models import RawProduct, variant_dim_index

            rraw = RawProduct(**_json.loads(snap["raw_json"]))
            if rraw.skus:
                dimn = list(rraw.skus[0].props.keys())[variant_dim_index(rraw)]
                groups: dict[str, list] = {}
                for s in rraw.skus:
                    if dimn in s.props:
                        groups.setdefault(s.props[dimn], []).append(s)
                omap = {r["option_zh"]: dict(r) for r in conn.execute(
                    "SELECT * FROM sku_options WHERE product_id=?", (pid,))}
                rate = ctx.settings.price_cny_to_rub
                for opt, grp in sorted(groups.items()):
                    cny = min((g.price_cny for g in grp if g.price_cny), default=0) or rraw.price_cny
                    variants.append({"zh": opt, "ru": omap.get(opt, {}).get("option_ru", ""),
                                     "price_rub": round(cny * rate), "combos": len(grp)})
        hero = next((r["translated_url"] for r in images
                     if r["kind"] == "main" and r["translated_url"]), None)
        from openoctopus.listing.enrich import parse_rich_content

        rich_blocks = parse_rich_content(p.get("rich_content") or "")
        content_jobs = conn.execute(
            "SELECT count(*) FROM jobs WHERE status IN ('queued','running') "
            "AND type IN ('regenerate_video','regenerate_rich') "
            "AND payload_json LIKE ?", (f'%"product_id": {pid}%',)).fetchone()[0]
        return TEMPLATES.TemplateResponse(request, "review.html",
                                          {"p": p, "t": t, "images": images, "hero": hero,
                                           "mapping": mapping, "cats": cats, "variants": variants,
                                           "rich_blocks": rich_blocks,
                                           "content_jobs": content_jobs,
                                           "currency": (ctx.settings.price_currency or "RUB").upper()})

    @app.post("/products/{pid}/edit")
    async def edit(request: Request, pid: int, title_ru: str = Form(...),
                   description_ru: str = Form(...),
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
