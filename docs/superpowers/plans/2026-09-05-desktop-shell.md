# Desktop Shell (pywebview) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python -m openoctopus desktop` opens the existing web workbench in a native window; double-click launcher needs no terminal.

**Architecture:** New `desktop.py` module starts uvicorn in a daemon thread, polls `/` until 200, then opens a pywebview window; closing the window ends the process. Existing `create_app`/`build_context` reused untouched.

**Tech Stack:** Python ≥3.11, uv, pywebview (macOS WebKit), uvicorn, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-09-05-desktop-shell-design.md`

## Global Constraints

- 复用现有 `create_app(build_context(get_settings()))`，不得改 web/ 采集/翻译/上架逻辑
- `import webview` 必须懒加载（函数内 import），缺依赖时打印 `uv sync` 提示并 `SystemExit(1)`
- 关窗即停服：服务线程必须是 daemon，无残留进程
- 端口被占不自动换端口，直接报错
- 服务 30s 未就绪抛 TimeoutError，退出码非零由调用方处理
- 每个 Task 以 commit 结束，测试全绿 + `uv run ruff check .` 通过才 commit
- 不写真实 GUI 测试；所有单测 mock webview/uvicorn/网络

---

### Task 1: desktop 模块 + desktop 子命令 + 单测

**Files:**
- Create: `src/openoctopus/desktop.py`
- Create: `tests/test_desktop.py`
- Modify: `src/openoctopus/__main__.py`（加 `desktop` 子命令分支）

**Interfaces:**
- Consumes: `create_app(ctx, run_worker=True)`, `build_context(settings)`, `get_settings()`
- Produces:
  - `check_port_free(host: str, port: int) -> None`（被占抛 RuntimeError）
  - `start_server_thread(app, host: str, port: int) -> threading.Thread`（daemon 线程跑 uvicorn）
  - `wait_ready(url: str, timeout: float = 30.0, client=None) -> True`（200 即返；超时抛 TimeoutError）
  - `run_desktop(host="127.0.0.1", port=8765, webview_mod=None, serve_fn=None, app=None) -> None`（app 为 None 时现场构建；serve_fn 默认起 daemon 线程）

- [ ] **Step 1: 写失败测试** `tests/test_desktop.py`

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_desktop.py -v`
Expected: FAIL (`ModuleNotFoundError: openoctopus.desktop` 或成员缺失)

- [ ] **Step 3: 实现** `src/openoctopus/desktop.py`

```python
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
        except Exception:
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
```

- [ ] **Step 4: 接线 `__main__.py`**

```python
sub.add_parser("desktop")
...
    if args.cmd == "desktop":
        from openoctopus.desktop import run_desktop

        run_desktop()
        return
```

- [ ] **Step 5: 通过 + lint**

Run: `uv run pytest tests/test_desktop.py -v && uv run pytest -q 2>&1 | tail -2 && uv run ruff check .`
Expected: 全部 PASS（全量 37+6=43 个左右），lint 干净

- [ ] **Step 6: Commit**

```bash
git add src/openoctopus/desktop.py src/openoctopus/__main__.py tests/test_desktop.py
git commit -m "feat: pywebview desktop shell with readiness gate"
```

---

### Task 2: 依赖 + 双击启动器 + 文档 + 真机验证

**Files:**
- Modify: `pyproject.toml`（经 `uv add pywebview`）
- Create: `scripts/OpenOctopus.command`（chmod +x，git 保留执行位）
- Modify: `README.md`（加桌面启动小节）

**Interfaces:**
- Consumes: Task 1 的 `run_desktop`

- [ ] **Step 1: 加依赖**

```bash
uv add pywebview
```

- [ ] **Step 2: 创建双击启动器** `scripts/OpenOctopus.command`

```bash
#!/bin/bash
cd "$(dirname "$0")/.."
exec uv run python -m openoctopus desktop
```

```bash
chmod +x scripts/OpenOctopus.command
```

- [ ] **Step 3: README 加一节**

```markdown
## 桌面启动（macOS）
双击 `scripts/OpenOctopus.command`（首次右键→打开以绕过 Gatekeeper），或：
uv run python -m openoctopus desktop
```

- [ ] **Step 4: 真机验证（手动，结论写进 commit message 或报告）**
  1. `uv run python -m openoctopus desktop` → 原生窗口出现看板页
  2. 关闭窗口 → `lsof -i :8765` 无输出（无残留）
  3. 双击 `.command` 文件 → 同样拉起窗口

- [ ] **Step 5: Commit + push**

```bash
git add pyproject.toml uv.lock scripts/OpenOctopus.command README.md
git commit -m "feat: one-click desktop launcher and docs"
git push
```
