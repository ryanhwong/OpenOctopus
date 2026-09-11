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
                            timeout_ms: int = 45000) -> list[str]:
    """用 playwright 抓 Ozon 搜索结果标题；失败返回 []。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []
    titles: list[str] = []
    try:
        async with async_playwright() as p:
            kwargs: dict = {"headless": True}
            if proxy:
                kwargs["proxy"] = {"server": proxy}
            browser = await p.chromium.launch(**kwargs)
            page = await browser.new_page(
                locale="ru-RU",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
            await page.goto(SEARCH_URL.format(q=quote(query)), timeout=timeout_ms,
                            wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            for el in await page.query_selector_all('a[href*="/product/"]'):
                t = (await el.inner_text()).strip().replace("\n", " ")
                if len(t) > 15 and t not in titles:
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
