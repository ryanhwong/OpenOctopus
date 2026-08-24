import asyncio
import json

MAX_RETRIES = 3


def enqueue(conn, type_: str, payload: dict) -> int:
    cur = conn.execute("INSERT INTO jobs(type, payload_json) VALUES(?,?)",
                       (type_, json.dumps(payload)))
    conn.commit()
    return cur.lastrowid


class JobRunner:
    def __init__(self, conn, handlers: dict, ctx=None):
        self.conn = conn
        self.handlers = handlers
        self.ctx = ctx

    async def run_once(self) -> bool:
        row = self.conn.execute(
            "SELECT id, type, payload_json, retries FROM jobs "
            "WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return False
        self.conn.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
        self.conn.commit()
        try:
            await self.handlers[row["type"]](self.ctx, json.loads(row["payload_json"]))
            self.conn.execute("UPDATE jobs SET status='done' WHERE id=?", (row["id"],))
        except Exception as e:  # noqa: BLE001
            retries = row["retries"] + 1
            status = "failed" if retries >= MAX_RETRIES else "queued"
            self.conn.execute("UPDATE jobs SET status=?, retries=?, error=? WHERE id=?",
                              (status, retries, str(e), row["id"]))
        self.conn.commit()
        return True

    async def run_forever(self, poll_interval: float = 2.0):
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(poll_interval)
