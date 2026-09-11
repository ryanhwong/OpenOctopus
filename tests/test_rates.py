from types import SimpleNamespace


def make_conn(tmp_path):
    from openoctopus.db import get_conn, init_db

    p = str(tmp_path / "r.db")
    init_db(p)
    return get_conn(p)


def test_rate_uses_fresh_cache(tmp_path):
    from openoctopus.rates import get_rate

    conn = make_conn(tmp_path)
    conn.execute("INSERT INTO settings_kv(key, value) VALUES('cny_rub_rate', '13.5')")
    conn.commit()
    assert get_rate(conn, 12.0) == 13.5


def test_rate_falls_back_on_error(tmp_path, monkeypatch):
    from openoctopus import rates

    def boom(*_a, **_kw):
        raise RuntimeError("no net")

    monkeypatch.setattr(rates.httpx, "get", boom)
    conn = make_conn(tmp_path)
    assert rates.get_rate(conn, 12.0) == 12.0


def test_rate_fetches_and_caches(tmp_path, monkeypatch):
    from openoctopus import rates

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"rates": {"RUB": 11.8}}

    monkeypatch.setattr(rates.httpx, "get", lambda *_a, **_kw: FakeResp())
    conn = make_conn(tmp_path)
    assert rates.get_rate(conn, 12.0) == 11.8
    row = conn.execute("SELECT value FROM settings_kv WHERE key='cny_rub_rate'").fetchone()
    assert row["value"] == "11.8"
    assert not isinstance(row, SimpleNamespace)
