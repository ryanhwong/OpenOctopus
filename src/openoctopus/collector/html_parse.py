import html as html_module
import re

from bs4 import BeautifulSoup

from openoctopus.models import RawProduct, Sku


def _first_number(text: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else 0.0


def _assert_human_page(soup: BeautifulSoup) -> None:
    title = soup.title.get_text().strip() if soup.title else ""
    low = title.lower()
    if any(k in low for k in ("captcha", "验证", "登录", "login", "passport", "authentication")):
        raise ValueError(f"1688 返回了验证/登录页（标题：{title[:60]}），请稍后重试或改用 HTML 导入兜底")


def _swatch_img(url: str | None) -> str:
    u = _norm_img(url)
    if u.endswith("_sum.jpg"):
        u = u[: -len("_sum.jpg")]
        if u.rsplit(".", 1)[-1].lower() not in ("jpg", "jpeg", "png", "webp"):
            u += ".jpg"
    return u


def _parse_dimensions(soup: BeautifulSoup) -> list[tuple[str, list[tuple[str, str]]]]:
    dims = []
    for fi in soup.select(".module-od-sku-selection .feature-item"):
        label = fi.select_one(".feature-item-label")
        name = label.get_text().strip() if label else ""
        opts = []
        for btn in fi.select(".sku-filter-button"):
            nm = btn.select_one(".label-name")
            im = btn.select_one("img")
            if nm and nm.get_text().strip():
                img = _swatch_img(im.get("src") or im.get("data-src")) if im else ""
                if img.startswith("http"):
                    opts.append((nm.get_text().strip(), img))
                elif nm.get_text().strip():
                    opts.append((nm.get_text().strip(), ""))
        if name and opts:
            dims.append((name, opts))
    return dims


def _extract_sku_map(html: str) -> list[dict]:
    import json as _json

    merged: dict[str, dict] = {}
    for key in ('"skuMapOriginal"', '"skuMap"'):
        idx = 0
        while True:
            idx = html.find(key, idx)
            if idx == -1:
                break
            start = html.find("[", idx)
            idx += len(key)
            if start == -1:
                continue
            depth, i = 0, start
            while i < len(html):
                if html[i] == "[":
                    depth += 1
                elif html[i] == "]":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            try:
                data = _json.loads(html[start:i + 1])
            except Exception:  # noqa: BLE001, S112
                continue
            if not isinstance(data, list):
                continue
            for c in data:
                if not isinstance(c, dict):
                    continue
                sid = str(c.get("skuId", ""))
                prev = merged.get(sid)
                if prev is None or _sku_price(c) > _sku_price(prev):
                    merged[sid or str(len(merged))] = c
    return list(merged.values())


def _sku_price(c: dict) -> float:
    try:
        return float(c.get("discountPrice") or c.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_skus(soup: BeautifulSoup, html: str) -> list[Sku]:
    dims = _parse_dimensions(soup)
    if not dims:
        return []
    swatch = {v: img for _, opts in dims for v, img in opts}
    skus = []
    for c in _extract_sku_map(html):
        attrs = html_module.unescape(str(c.get("specAttrs", ""))).split(">")
        props = {}
        for i, (dname, _) in enumerate(dims):
            if i < len(attrs) and attrs[i].strip():
                props[dname] = attrs[i].strip()
        if not props:
            continue
        price = _sku_price(c)
        first_val = props.get(dims[0][0], "")
        skus.append(Sku(props=props, price_cny=price, image_url=swatch.get(first_val)))
    return skus
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
    for sel in ('[class*="od-price"]', ".od-price", ".price"):
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
                                "div.detail-gallery img"])[:15]
    detail = _collect_imgs(soup, [".content-detail img"])
    if not title and not main and not detail:
        raise ValueError("页面中未找到商品标题与图片，可能被反爬拦截，请重试或改用 HTML 导入兜底")
    return RawProduct(source_url=source_url, platform="1688", title_zh=title,
                      price_cny=price, main_images=main, detail_images=detail,
                      skus=_parse_skus(soup, html))
