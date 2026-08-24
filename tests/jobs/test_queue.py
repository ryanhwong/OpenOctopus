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
