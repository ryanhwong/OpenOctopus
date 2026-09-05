import socket
import threading
import time

import httpx
import uvicorn

WINDOW_TITLE = "OpenOctopus"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 900
READY_TIMEOUT = 30.0


def check_port_free(host: str, port: int) -> None:
    with socket.socket() as s:
        try:
            s.bind((host, port))
        except OSError:
            raise RuntimeError(f"端口 {port} 已被占用，先停掉旧服务再启动")


def start_server_thread(app, host: str, port: int) -> threading.Thread:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True, name="openoctopus-server")
    t.start()
    return t


def default_serve(app, host: str, port: int):
    return start_server_thread(app, host, port)


def wait_ready(url: str, timeout: float = READY_TIMEOUT, client=None) -> bool:
    get = client.get if client is not None else httpx.get
    deadline = time.monotonic() + timeout
    while True:
        try:
            if get(url, timeout=2).status_code == 200:
                return True
        except Exception:  # noqa: BLE001, S110
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(f"服务 {timeout}s 内未就绪：{url}")
        time.sleep(0.5)


def run_desktop(host: str = "127.0.0.1", port: int = 8765,
                webview_mod=None, serve_fn=None, app=None) -> None:
    if webview_mod is None:
        try:
            import webview as webview_mod
        except ImportError:
            print("缺少 pywebview，先跑：uv sync")
            raise SystemExit(1)
    serve = serve_fn or default_serve

    if app is None:
        from openoctopus.config import get_settings
        from openoctopus.jobs.context import build_context
        from openoctopus.web.app import create_app

        app = create_app(build_context(get_settings()), run_worker=True)

    check_port_free(host, port)
    url = f"http://{host}:{port}"
    serve(app, host, port)
    wait_ready(url)
    webview_mod.create_window(WINDOW_TITLE, url, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT)
    webview_mod.start()
