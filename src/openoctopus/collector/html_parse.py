import re

from bs4 import BeautifulSoup

from openoctopus.models import RawProduct


def _first_number(text: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else 0.0


def parse_product_html(html: str, source_url: str) -> RawProduct:
    soup = BeautifulSoup(html, "html.parser")
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

    return RawProduct(source_url=source_url, platform="1688", title_zh=title,
                      price_cny=price, main_images=main, detail_images=detail)
