"""Ozon 卡片增强：属性填充 + Rich-контент JSON 生成。"""

import json

BRAND_WORDS = ("apple", "iwatch", "samsung", "xiaomi", "huawei", "galaxy")

COUNTRY_CHINA = 90296
MATERIAL_SILICONE = 43105
MATERIAL_TEXTILE = 43106
WARRANTY_1Y = 970716397
FITS_APPLE = 39477
SERIAL_NO = 82353


def build_rich_content(title_ru: str, description_ru: str,
                       image_urls: list[str], material_hint: str = "") -> str:
    """生成 Ozon rich-content JSON（raShowcase/chess，2-6 个图文块）。"""
    img = [u for u in image_urls if u][:4]
    if len(img) < 2:
        return ""
    paras = [p.strip() for p in (description_ru or "").split("\n") if p.strip()]
    if not paras:
        paras = [title_ru]
    blocks = []
    for i, url in enumerate(img):
        text = paras[i % len(paras)]
        blocks.append({
            "img": {"src": url, "srcMobile": url,
                    "width": 1080, "height": 1080,
                    "widthMobile": 640, "heightMobile": 640},
            "title": {"content": [title_ru[:60] if i == 0 else material_hint or title_ru[:40]],
                      "size": "size4", "align": "left", "color": "color1"},
            "text": {"size": "size2", "align": "left", "color": "color1",
                     "content": [text[:400]]},
            "reverse": i % 2 == 1,
        })
    return json.dumps({"version": 0.3,
                       "content": [{"widgetName": "raShowcase", "type": "chess",
                                    "blocks": blocks}]},
                      ensure_ascii=False)


def safe_hashtags(*words: str) -> str:
    """从词列表生成 hashtag，剔除品牌词。"""
    tags = []
    for w in words:
        w = w.strip().lower().replace(" ", "").replace("-", "")
        if not w or any(b in w for b in BRAND_WORDS):
            continue
        tags.append("#" + w)
    return " ".join(dict.fromkeys(tags))[:200]


def build_extra_attributes(*, description_ru: str, title_ru: str, weight_g: float | None,
                           length_mm: float | None, width_mm: float | None,
                           height_mm: float | None, material: str = "silicone",
                           video_url: str = "", rich_content: str = "",
                           hashtags: str = "") -> list[dict]:
    """返回可选的补充属性（各变体保持一致）。"""
    attrs: list[dict] = []

    def add(aid: int, value: str | None = None, dict_id: int | None = None):
        if dict_id is not None:
            attrs.append({"complex_id": 0, "id": aid,
                          "values": [{"dictionary_value_id": dict_id}]})
        elif value:
            attrs.append({"complex_id": 0, "id": aid, "values": [{"value": value}]})

    add(4191, value=(description_ru or title_ru)[:6000])
    if weight_g:
        add(4383, value=str(round(weight_g)))
        add(4382, value=f"{int(length_mm or 0)}x{int(width_mm or 0)}x{int(height_mm or 0)}")
    add(4389, dict_id=COUNTRY_CHINA)
    add(7978, dict_id=MATERIAL_TEXTILE if material == "textile" else MATERIAL_SILICONE)
    add(9591, value="22")
    add(8125, value="220")
    add(10400, dict_id=WARRANTY_1Y)
    add(22896, dict_id=FITS_APPLE)
    add(23489, dict_id=SERIAL_NO)
    add(4384, value="1 ремешок")
    add(11650, value="1")
    add(23249, value="1")
    add(6036, value="1")
    if hashtags:
        add(23171, value=hashtags)
    if video_url:
        add(21841, value=video_url)
        add(21845, value=video_url)
    if rich_content:
        add(11254, value=rich_content)
    return attrs
