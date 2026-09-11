"""Ozon 搜索关键词获取（best-effort）：抓搜索页商品标题 → LLM 提炼买家搜索词。

出口 IP 被 Ozon WAF 拦截时静默跳过（需在 .env 配 OZON_SCRAPE_PROXY 走可用的出口）。
"""

import json
import sys
from urllib.parse import quote

from openoctopus.llm_json import first_content, parse_json

SEARCH_URL = "https://www.ozon.ru/search/?text={q}"

KEYWORD_PROMPT = (
    "You are an Ozon.ru SEO expert. From the competitor product titles below, "
    "extract 8-12 Russian search keywords/phrases that buyers actually type "
    "(e.g. 'ремешок для apple watch', 'браслет для часов'). "
    "No brand-official claims, no duplicates, lowercase, max 5 words per phrase. "
    'Respond strict JSON: {"keywords": [str]}'
)


async def fetch_ozon_titles(query: str, proxy: str = "", limit: int = 10,
                            timeout_ms: int = 60000) -> list[str]:
    """抓 Ozon 搜索结果标题。

    用真实 Chrome + 有头模式绕过 antibot；不读环境代理（走真直连）。
    失败返回 []，不影响主流程。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []
    titles: list[str] = []
    try:
        async with async_playwright() as p:
            launch_kwargs: dict = {}
            if proxy:
                launch_kwargs["proxy"] = {"server": proxy}
            try:
                browser = await p.chromium.launch(
                    channel="chrome", headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                    **launch_kwargs)
            except Exception:  # noqa: BLE001
                browser = await p.chromium.launch(headless=True, **launch_kwargs)
            ctx = await browser.new_context(
                locale="ru-RU", viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
            page = await ctx.new_page()
            await page.goto(SEARCH_URL.format(q=quote(query)), timeout=timeout_ms,
                            wait_until="domcontentloaded")
            await page.wait_for_timeout(6000)
            for el in await page.query_selector_all('a[href*="/product/"]'):
                t = " ".join((await el.inner_text()).split())
                if len(t) < 25 or t in titles:
                    continue
                titles.append(t[:150])
                if len(titles) >= limit:
                    break
            await browser.close()
    except Exception as e:  # noqa: BLE001
        print(f"[keywords] ozon fetch failed: {e}", file=sys.stderr)
        return []
    return titles


async def extract_keywords(client, model, titles: list[str]) -> list[str]:
    """从竞品标题提炼搜索词。"""
    if not titles:
        return []
    user = json.dumps({"titles": titles[:15]}, ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": KEYWORD_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.2)
    data = parse_json(first_content(resp))
    out = []
    for k in data.get("keywords", []):
        k = str(k).strip().lower()
        if k and k not in out:
            out.append(k[:60])
    return out[:12]
