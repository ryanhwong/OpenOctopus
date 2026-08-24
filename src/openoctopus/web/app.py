import json as _json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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

    @app.get("/", response_class=HTMLResponse)
    def kanban(request: Request):
        conn = get_conn(ctx.db_path)
        groups = [(label, conn.execute(
            "SELECT id, source_url FROM products WHERE status=? ORDER BY updated_at DESC",
            (st,)).fetchall()) for st, label in STATUS_GROUPS]
        return TEMPLATES.TemplateResponse(request, "kanban.html", {"groups": groups})

    @app.post("/products")
    def submit(url: str = Form(...)):
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
        cats = conn.execute("SELECT id, title FROM ozon_categories ORDER BY title LIMIT 500").fetchall()
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
            "INSERT INTO category_mappings(product_id, ozon_category_id, attributes_json, human_confirmed)"
            " VALUES(?,?,?,1) ON CONFLICT(product_id) DO UPDATE SET "
            "ozon_category_id=excluded.ozon_category_id, attributes_json=excluded.attributes_json,"
            " human_confirmed=1", (pid, ozon_category_id, _json.dumps(attrs, ensure_ascii=False)))
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/approve")
    def approve(pid: int):
        conn = get_conn(ctx.db_path)
        conn.execute("UPDATE products SET status='publishing' WHERE id=?", (pid,))
        conn.commit()
        enqueue(conn, "publish", {"product_id": pid})
        return RedirectResponse("/", status_code=303)

    @app.post("/products/{pid}/regenerate")
    def regenerate(pid: int):
        conn = get_conn(ctx.db_path)
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
