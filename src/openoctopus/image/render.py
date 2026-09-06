import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from openoctopus.models import TextBox


def erase_boxes(img: Image.Image, boxes: list[TextBox]) -> Image.Image:
    arr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    mask = np.zeros(arr.shape[:2], np.uint8)
    for b in boxes:
        x0, y0, x1, y1 = _label_box(img, b)
        mask[y0:y1, x0:x1] = 255
    if boxes:
        arr = cv2.inpaint(arr, mask, 10, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _bg_color(img: Image.Image, b: TextBox, pad: int = 8) -> tuple[int, int, int]:
    x0, y0 = max(0, b.x - pad), max(0, b.y - pad)
    x1, y1 = min(img.width, b.x + b.w + pad), min(img.height, b.y + b.h)
    region = np.array(img.crop((x0, y0, x1, y1))).reshape(-1, 3)
    med = np.median(region, axis=0)
    return tuple(int(c) for c in med)


def _contrast_text_color(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (30, 30, 30) if lum > 130 else (245, 245, 245)


def _label_box(img: Image.Image, b: TextBox, pad_ratio: float = 0.25) -> tuple[int, int, int, int]:
    pad_w, pad_h = int(b.w * pad_ratio), int(b.h * pad_ratio)
    x0, y0 = max(0, b.x - pad_w), max(0, b.y - pad_h)
    x1, y1 = min(img.width, b.x + b.w + pad_w), min(img.height, b.y + b.h + pad_h)
    return x0, y0, x1, y1


def _rects_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _cluster_boxes(img: Image.Image, boxes: list[TextBox]) -> list[list[TextBox]]:
    """外扩矩形相交的框并成一簇，共用一块排版面板。"""
    rects = [_label_box(img, b) for b in boxes]
    parent = list(range(len(boxes)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _rects_overlap(rects[i], rects[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[TextBox]] = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b)
    return list(groups.values())


def _union_rect(img: Image.Image, cluster: list[TextBox]) -> tuple[int, int, int, int]:
    x0 = max(0, min(_label_box(img, b)[0] for b in cluster))
    y0 = max(0, min(_label_box(img, b)[1] for b in cluster))
    x1 = min(img.width, max(_label_box(img, b)[2] for b in cluster))
    y1 = min(img.height, max(_label_box(img, b)[3] for b in cluster))
    return x0, y0, x1, y1


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            cand = (cur + " " + word).strip()
            if not cur or draw.textlength(cand, font=font) <= max_w:
                cur = cand
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines or [""]


def _draw_panel(img: Image.Image, cluster: list[TextBox], font_path: str) -> None:
    """一簇文字共用一块面板：背景取色 + 自动换行排版 + 羽化边缘。无译文的簇只擦不画。"""
    texts = [b.ru_text for b in cluster if b.ru_text]
    if not texts:
        return
    bg = _bg_color(img, cluster[0])
    x0, y0, x1, y1 = _union_rect(img, cluster)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    fg = _contrast_text_color(bg)
    size = max(8, h // max(1, len(texts) * 2))
    lines: list[str] = []
    while size >= 8:
        f = ImageFont.truetype(font_path, size)
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        lines = []
        for t in texts:
            lines.extend(_wrap_lines(probe, t, f, w - 8))
        asc, desc = f.getmetrics()
        if len(lines) * (asc + desc + 2) <= h:
            break
        size -= 1
    else:
        return
    panel = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(panel)
    asc, desc = f.getmetrics()
    lh = asc + desc + 2
    total = len(lines) * lh
    y = max(0, (h - total) // 2)
    for line in lines:
        tw = d.textlength(line, font=f)
        d.text((max(0, (w - tw) // 2), y), line, font=f, fill=fg)
        y += lh
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle([0, 0, w - 1, h - 1], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, min(w, h) // 10)))
    img.paste(panel, (x0, y0), mask)


def draw_translations(img: Image.Image, boxes: list[TextBox], font_path: str) -> Image.Image:
    out = img.convert("RGB").copy()
    for cluster in _cluster_boxes(out, boxes):
        _draw_panel(out, cluster, font_path)
    return out


def translate_image_bytes(data: bytes, boxes: list[TextBox], font_path: str) -> bytes:
    with Image.open(io.BytesIO(data)) as src:
        img = src.convert("RGB")
    erased = erase_boxes(img, boxes)
    out = draw_translations(erased, boxes, font_path)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()
