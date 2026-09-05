import asyncio
from pathlib import Path

from openoctopus.collector.base import register
from openoctopus.collector.html_parse import parse_product_html
from openoctopus.config import get_settings
from openoctopus.models import RawProduct


@register
class A1688PlaywrightAdapter:
    platform = "1688"

    @staticmethod
    def matches(url: str) -> bool:
        host = url.split("/")[2] if "://" in url else ""
        return host == "1688.com" or host.endswith(".1688.com")

    async def fetch(self, url: str) -> RawProduct:
        if not get_settings().live_mode:
            raise RuntimeError("LIVE_MODE=0: 真实抓取被禁止")
        html = await asyncio.to_thread(self._fetch_sync, url)
        return parse_product_html(html, url)

    def _fetch_sync(self, url: str) -> str:
        from bs4 import BeautifulSoup
        from playwright.sync_api import sync_playwright

        s = get_settings()
        state = Path(s.playwright_storage_state)
        state_existed = state.exists()
        launch_kw: dict = {"headless": True}
        if Path("/Applications/Google Chrome.app").exists():
            launch_kw["channel"] = "chrome"
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kw)
            ctx = browser.new_context(
                storage_state=str(state) if state_existed else None,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            html = page.content()

            soup = BeautifulSoup(html, "html.parser")
            og = soup.select_one('meta[property="og:title"]')
            title_text = (og.get("content") if og else "").strip()
            is_login_wall = "登录" in title_text or "login" in title_text.lower()
            if state_existed and og is not None and not is_login_wall:
                ctx.storage_state(path=str(state))
            browser.close()
        return html
