import socket
import threading

import pytest

from openoctopus import desktop as d


class Resp:
    status_code = 200


class Flaky:
    def __init__(self, fails):
        self.fails = fails
        self.calls = 0

    def get(self, url, timeout=2):
        self.calls += 1
        if self.calls <= self.fails:
            raise ConnectionError("down")
        return Resp()


class AlwaysDown:
    def get(self, url, timeout=2):
        raise ConnectionError("down")


def test_wait_ready_immediate():
    assert d.wait_ready("http://x/", client=Flaky(0)) is True


def test_wait_ready_retries():
    c = Flaky(2)
    assert d.wait_ready("http://x/", client=c) is True
    assert c.calls == 3


def test_wait_ready_timeout():
    with pytest.raises(TimeoutError):
        d.wait_ready("http://x/", timeout=0.1, client=AlwaysDown())


def test_check_port_free_raises():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        with pytest.raises(RuntimeError):
            d.check_port_free("127.0.0.1", port)
    finally:
        s.close()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_run_desktop_orchestrates(monkeypatch):
    calls = {}

    class FakeWebview:
        def create_window(self, title, url, width=None, height=None):
            calls["window"] = (title, url, width, height)

        def start(self):
            calls["started"] = True

    def fake_serve(app, host, port):
        calls["serve"] = (app, host, port)
        return threading.Thread()

    monkeypatch.setattr(d, "wait_ready", lambda url, timeout=30.0, client=None: True)
    port = free_port()
    d.run_desktop(port=port, webview_mod=FakeWebview(), serve_fn=fake_serve, app=object())
    assert calls["serve"][1:] == ("127.0.0.1", port)
    assert calls["window"] == ("OpenOctopus", f"http://127.0.0.1:{port}", 1280, 900)
    assert calls["started"] is True
