import pytest

from openoctopus.db import get_conn, init_db
from openoctopus.jobs.queue import JobRunner, enqueue


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "j.db")
    init_db(p)
    return get_conn(p)


async def test_done_and_retry_paths(db):
    calls = []

    async def ok(ctx, payload):
        calls.append(payload["n"])

    async def boom(ctx, payload):
        raise RuntimeError("x")

    enqueue(db, "ok", {"n": 1})
    enqueue(db, "boom", {})
    r = JobRunner(db, {"ok": ok, "boom": boom})
    await r.run_once()
    await r.run_once()
    assert calls == [1]
    st = {row["type"]: row["status"] for row in db.execute("SELECT * FROM jobs")}
    assert st["ok"] == "done"
    assert st["boom"] == "queued"

    for i in range(2):
        db.execute("UPDATE jobs SET status='queued' WHERE type='boom'")
        db.commit()
        await r.run_once()
    db.execute("UPDATE jobs SET status='queued' WHERE type='boom' AND retries<3")
    db.commit()
    await r.run_once()
    row = db.execute("SELECT * FROM jobs WHERE type='boom'").fetchone()
    assert row["status"] == "failed" and row["error"] == "x" and row["retries"] == 3


async def test_run_once_from_other_thread(db):
    """桌面版 uvicorn 跑在子线程：runner 连接必须跨线程可用。"""
    import asyncio
    import threading

    calls = []

    async def ok(ctx, payload):
        calls.append(1)

    enqueue(db, "ok", {})
    r = JobRunner(db, {"ok": ok})
    outcome = {}

    def target():
        try:
            outcome["worked"] = asyncio.run(r.run_once())
        except Exception as e:  # noqa: BLE001
            outcome["error"] = e

    t = threading.Thread(target=target)
    t.start()
    t.join(timeout=10)
    assert "error" not in outcome, outcome.get("error")
    assert outcome.get("worked") is True and calls == [1]


async def test_transient_error_backs_off(db, monkeypatch):
    import asyncio as _asyncio

    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(_asyncio, "sleep", fake_sleep)

    async def flaky(ctx, payload):
        raise RuntimeError("provider overloaded, try later")

    enqueue(db, "flaky", {})
    r = JobRunner(db, {"flaky": flaky}, backoff_base=45.0)
    assert await r.run_once() is True
    assert slept == [45.0]
    row = db.execute("SELECT status, retries FROM jobs").fetchone()
    assert row["status"] == "queued" and row["retries"] == 1


async def test_perm_error_no_backoff(db, monkeypatch):
    import asyncio as _asyncio

    slept = []
    monkeypatch.setattr(_asyncio, "sleep", lambda s: slept.append(s))

    async def bad(ctx, payload):
        raise ValueError("bad config")

    enqueue(db, "bad", {})
    r = JobRunner(db, {"bad": bad}, backoff_base=45.0)
    await r.run_once()
    assert slept == []
