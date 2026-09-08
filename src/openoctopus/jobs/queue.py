import asyncio
import json

MAX_RETRIES = 3


def enqueue(conn, type_: str, payload: dict) -> int:
    cur = conn.execute("INSERT INTO jobs(type, payload_json) VALUES(?,?)",
                       (type_, json.dumps(payload)))
    conn.commit()
    return cur.lastrowid


class JobRunner:
    # 瞬时错误（限流/过载/超时）退避重试；单 worker 下 sleep 会阻塞队列，
    # 但比重试全砸在同一拥堵窗口里要好。测试用 backoff_base=0 跳过等待。
    TRANSIENT_MARKERS = ("no choices", "overloaded", "rate limit", "429",
                         "timeout", "timed out", "try later", "temporarily",
                         "upstream", "unavailable")

    def __init__(self, conn, handlers: dict, ctx=None, backoff_base: float = 0.0):
        self.conn = conn
        self.handlers = handlers
        self.ctx = ctx
        self.backoff_base = backoff_base

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
            if status == "queued" and self._is_transient(e):
                await asyncio.sleep(min(300, self.backoff_base * (2 ** row["retries"])))
            self.conn.execute("UPDATE jobs SET status=?, retries=?, error=? WHERE id=?",
                              (status, retries, str(e), row["id"]))
        self.conn.commit()
        return True

    @classmethod
    def _is_transient(cls, e: Exception) -> bool:
        msg = str(e).lower()
        return any(m in msg for m in cls.TRANSIENT_MARKERS)

    async def run_forever(self, poll_interval: float = 2.0):
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(poll_interval)
