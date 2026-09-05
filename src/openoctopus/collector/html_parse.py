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


def _norm_img(u: str | None) -> str:
    u = (u or "").strip()
    if u.startswith("//"):
        u = "https:" + u
    # 阿里图片服务的 _.webp 后缀去掉即回原格式（Ozon 对 webp 支持不稳定）
    suffix = "_.webp"
    if u.endswith(suffix) and u[:-len(suffix)].rsplit(".", 1)[-1].lower() in ("jpg", "jpeg", "png"):
        u = u[: -len(suffix)]
    return u


def _collect_imgs(soup: BeautifulSoup, selectors: list[str]) -> list[str]:
    out: list[str] = []
    for sel in selectors:
        for img in soup.select(sel):
            u = _norm_img(img.get("data-src") or img.get("src"))
            if not u.startswith("http") or u.lower().endswith(".svg"):
                continue
            if u not in out:
                out.append(u)
    return out


def _extract_title(soup: BeautifulSoup) -> str:
    if (tag := soup.select_one('meta[property="og:title"]')) and tag.get("content", "").strip():
        return tag.get("content", "").strip()
    node = soup.select_one(".module-od-title .title-content") or soup.select_one(".module-od-title")
    if node and node.get_text().strip():
        return node.get_text().strip()
    if soup.title:
        t = re.sub(r"\s*[-–|]\s*阿里巴巴\s*$", "", soup.title.get_text().strip())
        # 过短的标题（如裸 "1688"）视为无商品内容，交给兜底报错
        return t if len(t) >= 6 else ""
    return ""


def _extract_price(soup: BeautifulSoup) -> float:
    for sel in (".od-price", ".price"):
        node = soup.select_one(sel)
        if node and (v := _first_number(node.get_text())):
            return v
    return 0.0


def parse_product_html(html: str, source_url: str) -> RawProduct:
    soup = BeautifulSoup(html, "html.parser")
    _assert_human_page(soup)
    title = _extract_title(soup)
    price = _extract_price(soup)
    main = _collect_imgs(soup, [".od-gallery-preview img", ".od-gallery-list img",
                                "div.detail-gallery img"])
    detail = _collect_imgs(soup, [".content-detail img"])
    if not title and not main and not detail:
        raise ValueError("页面中未找到商品标题与图片，可能被反爬拦截，请重试或改用 HTML 导入兜底")
    return RawProduct(source_url=source_url, platform="1688", title_zh=title,
                      price_cny=price, main_images=main, detail_images=detail)
