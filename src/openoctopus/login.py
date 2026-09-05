import argparse
import threading
from pathlib import Path


class LoginSession:
    """一次 1688 扫码登录会话：后台线程开浏览器，主线程调 finish() 存盘。

    Playwright 同步 API 的 launch 与存盘必须在同一线程内完成，
    因此浏览器整个生命周期都跑在这个 session 自建的线程里。
    """

    def __init__(self, state_path: str, url: str = "https://www.1688.com"):
        self.state_path = state_path
        self.url = url
        self.status = "idle"  # idle|waiting|done|error
        self.error = ""
        self._event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.status == "waiting":
            return
        self.status = "waiting"
        self.error = ""
        self._event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto(self.url)
                self._event.wait(timeout=600)
                Path(self.state_path).parent.mkdir(parents=True, exist_ok=True)
                ctx.storage_state(path=self.state_path)
                browser.close()
            self.status = "done"
        except Exception as e:  # noqa: BLE001
            self.status = "error"
            self.error = str(e)

    def finish(self, timeout: float = 10.0) -> bool:
        if self.status != "waiting":
            return self.status == "done"
        self._event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        return self.status == "done"


def verify_login(state_path: str) -> bool:
    """用已存登录态无头访问会员中心：没被踢到登录页即视为有效。"""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=state_path)
            page = ctx.new_page()
            page.goto("https://member.1688.com/", wait_until="domcontentloaded", timeout=30000)
            final = page.url
            browser.close()
        host = final.split("/")[2] if "://" in final else ""
        return "login" not in host and "passport" not in host and "auth" not in host
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="openoctopus-login")
    parser.add_argument("--url", default="https://www.1688.com")
    args = parser.parse_args(argv)

    from openoctopus.config import get_settings

    state = Path(get_settings().playwright_storage_state)
    state.parent.mkdir(parents=True, exist_ok=True)

    session = LoginSession(str(state), args.url)
    session.start()
    print("请在浏览器中完成登录（扫码），然后回到终端按回车…")
    input()
    session.finish()
    print(f"登录态已保存到 {state}")


if __name__ == "__main__":
    main()
