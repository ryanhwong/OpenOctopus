import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="openoctopus-login")
    parser.add_argument("--url", default="https://www.1688.com")
    args = parser.parse_args()

    from openoctopus.config import get_settings

    state = Path(get_settings().playwright_storage_state)
    state.parent.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(args.url)
        print("请在浏览器中完成登录（扫码），然后回到终端按回车…")
        input()
        ctx.storage_state(path=str(state))
        browser.close()
    print(f"登录态已保存到 {state}")


if __name__ == "__main__":
    main()
