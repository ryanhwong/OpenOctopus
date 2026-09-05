import re

from bs4 import BeautifulSoup

from openoctopus.models import RawProduct


def _first_number(text: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else 0.0


def _assert_human_page(soup: BeautifulSoup) -> None:
    title = soup.title.get_text().strip() if soup.title else ""
    low = title.lower()
    if any(k in low for k in ("captcha", "验证", "登录", "login", "passport", "authentication")):
        raise ValueError(f"1688 返回了验证/登录页（标题：{title[:60]}），请稍后重试或改用 HTML 导入兜底")


def parse_product_html(html: str, source_url: str) -> RawProduct:
    soup = BeautifulSoup(html, "html.parser")
    _assert_human_page(soup)
    title = ""
    if tag := soup.select_one('meta[property="og:title"]'):
        title = tag.get("content", "").strip()
    price = _first_number(soup.select_one(".price").get_text() if soup.select_one(".price") else "")

    main = []
    for img in soup.select("div.detail-gallery img[src]"):
        if img["src"] not in main:
            main.append(img["src"])

    detail = []
    for img in soup.select(".content-detail img"):
        u = img.get("data-src") or img.get("src") or ""
        if u.startswith("//"):
            u = "https:" + u
        if u and u not in detail:
            detail.append(u)

    if not title and not main and not detail:
        raise ValueError("页面中未找到商品标题与图片，可能被反爬拦截，请重试或改用 HTML 导入兜底")

    return RawProduct(source_url=source_url, platform="1688", title_zh=title,
                      price_cny=price, main_images=main, detail_images=detail)
