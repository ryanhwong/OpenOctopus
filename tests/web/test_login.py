from types import SimpleNamespace
from typing import ClassVar

from fastapi.testclient import TestClient

import openoctopus.login as login_mod
from openoctopus.config import Settings
from openoctopus.db import get_conn, init_db
from openoctopus.web.app import create_app


class FakeSession:
    instances: ClassVar[list] = []

    def __init__(self, state_path, url="https://www.1688.com"):
        self.state_path = state_path
        self.url = url
        self.status = "idle"
        FakeSession.instances.append(self)

    def start(self):
        self.status = "waiting"

    def finish(self, timeout=10.0):
        self.status = "done"
        return True


def make_client(tmp_path, monkeypatch, verified=True):
    FakeSession.instances.clear()
    monkeypatch.setattr(login_mod, "LoginSession", FakeSession)
    monkeypatch.setattr(login_mod, "verify_login", lambda path: verified)
    db_path = str(tmp_path / "l.db")
    init_db(db_path)
    settings = Settings(_env_file=None, playwright_storage_state=str(tmp_path / "state.json"))
    ctx = SimpleNamespace(settings=settings, db_path=db_path)
    return TestClient(create_app(ctx, run_worker=False))


def test_start_login_shows_waiting(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch)
    assert c.post("/login/start", follow_redirects=False).status_code == 303
    st = c.get("/login/status").json()
    assert st["status"] == "waiting" and st["logged_in"] is False
    assert "等待扫码" in c.get("/").text


def test_finish_login_marks_logged_in(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch)
    c.post("/login/start")
    assert c.post("/login/finish", follow_redirects=False).status_code == 303
    st = c.get("/login/status").json()
    assert st["status"] == "done" and st["logged_in"] is True
    assert "已登录" in c.get("/").text


def test_finish_without_start_is_noop(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch)
    assert c.post("/login/finish", follow_redirects=False).status_code == 303
    assert c.get("/login/status").json()["status"] == "idle"


def test_verify_failed_shows_warning(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch, verified=False)
    c.post("/login/start")
    c.post("/login/finish")
    assert c.get("/login/status").json()["logged_in"] is False
    assert "未能验证" in c.get("/").text


def test_existing_state_file_counts_as_logged_in(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch)
    (tmp_path / "state.json").write_text("{}")
    assert "已登录" in c.get("/").text
    conn = get_conn(str(tmp_path / "l.db"))
    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 0
