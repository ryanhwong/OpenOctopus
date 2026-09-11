"""CNY→RUB 汇率：在线拉取 + DB 缓存（24h），失败回退旧值/配置。"""

import sys

import httpx

RATE_URL = "https://open.er-api.com/v6/latest/CNY"
CACHE_KEY = "cny_rub_rate"


def get_rate(conn, fallback: float, ttl_hours: int = 24) -> float:
    """返回当前汇率；优先缓存，过期在线刷新，失败用旧值或 fallback。"""
    rate = 0.0
    row = None
    try:
        row = conn.execute(
            "SELECT value, (julianday('now') - julianday(updated_at)) * 24 AS age_h "
            "FROM settings_kv WHERE key=?", (CACHE_KEY,)).fetchone()
    except Exception:  # noqa: BLE001
        row = None
    if row and row["value"]:
        try:
            rate = float(row["value"]) or 0.0
        except (TypeError, ValueError):
            rate = 0.0
        if rate and row["age_h"] is not None and row["age_h"] < ttl_hours:
            return rate
    try:
        r = httpx.get(RATE_URL, timeout=6)
        r.raise_for_status()
        live = float(r.json()["rates"]["RUB"])
        if live > 0:
            conn.execute(
                "INSERT INTO settings_kv(key, value, updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=CURRENT_TIMESTAMP", (CACHE_KEY, str(live)))
            conn.commit()
            return live
    except Exception as e:  # noqa: BLE001
        print(f"[rates] fetch failed: {e}", file=sys.stderr)
    return rate or fallback
