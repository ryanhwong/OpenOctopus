import json as _json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from openoctopus import login as login_mod
from openoctopus.db import get_conn, init_db
from openoctopus.jobs.handlers import HANDLERS, collect_from_html, upsert_translation
from openoctopus.jobs.queue import JobRunner, enqueue

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATUS_GROUPS = [("new", "待处理"), ("collected", "已采集"), ("generating", "生成中"),
                 ("review", "待审"), ("publishing", "发布中"), ("listed", "已上架"),
                 ("failed", "失败")]


def create_app(ctx, run_worker: bool = True) -> FastAPI:
    init_db(ctx.db_path)
    app = FastAPI()
    runner = JobRunner(get_conn(ctx.db_path), HANDLERS, ctx)
    app.state.login_session = None
    app.state.login_info = {"status": "idle", "logged_in": False, "checked_at": None}

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
    def kanban(request: Request):
        conn = get_conn(ctx.db_path)
        groups = [(label, conn.execute(
            "SELECT id, source_url FROM products WHERE status=? ORDER BY updated_at DESC",
            (st,)).fetchall()) for st, label in STATUS_GROUPS]
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
        return TEMPLATES.TemplateResponse(request, "kanban.html", {"groups": groups,
                                                                     "login": _login_snapshot(),
                                                                     "jobs": job_by_product})

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
        return TEMPLATES.TemplateResponse(request, "review.html",
                                          {"p": p, "t": t, "images": images,
                                           "mapping": mapping, "cats": cats})

    @app.post("/products/{pid}/edit")
    def edit(pid: int, title_ru: str = Form(...), description_ru: str = Form(...),
             price_rub: str = Form(""), ozon_category_id: str = Form(...),
             attributes_json: str = Form("{}")):
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
        if price_rub != "":
            try:
                price_rub_val = float(price_rub)
            except ValueError:
                return HTMLResponse("Invalid price_rub", status_code=400)
        else:
            price_rub_val = None
        conn = get_conn(ctx.db_path)
        upsert_translation(conn, pid, "title", "", title_ru)
        upsert_translation(conn, pid, "description", "", description_ru)
        if price_rub_val is not None:
            conn.execute("UPDATE products SET price_rub=? WHERE id=?", (price_rub_val, pid))
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
        if row["status"] not in ("review", "collected", "generating"):
            return HTMLResponse(
                "Approve only allowed in review/collected/generating status",
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
        if row["status"] not in ("review", "collected", "generating"):
            return HTMLResponse(
                "Regenerate only allowed in review/collected/generating status",
                status_code=400)
        conn.execute("UPDATE products SET status='generating' WHERE id=?", (pid,))
        conn.commit()
        enqueue(conn, "generate", {"product_id": pid})
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/jobs/{jid}/retry")
    def retry(jid: int):
        conn = get_conn(ctx.db_path)
        conn.execute("UPDATE jobs SET status='queued', error=NULL WHERE id=?", (jid,))
        conn.commit()
        return RedirectResponse("/", status_code=303)

    return app
