import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

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


def _fit_font(
    draw: ImageDraw.ImageDraw, text: str, box_w: int, box_h: int, font_path: str
) -> ImageFont.FreeTypeFont:
    lo, hi = 8, max(8, box_h)
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(font_path, mid)
        if draw.textlength(text, font=f) <= box_w and sum(f.getmetrics()) <= box_h:
            best = f
            lo = mid + 1
        else:
            hi = mid - 1
    return best or ImageFont.truetype(font_path, 8)


def _bg_color(img: Image.Image, b: TextBox, pad: int = 8) -> tuple[int, int, int]:
    x0, y0 = max(0, b.x - pad), max(0, b.y - pad)
    x1, y1 = min(img.width, b.x + b.w + pad), min(img.height, b.y + b.h)
    region = np.array(img.crop((x0, y0, x1, y1))).reshape(-1, 3)
    med = np.median(region, axis=0)
    return tuple(int(c) for c in med)


def _contrast_text_color(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
    return (30, 30, 30) if lum > 130 else (245, 245, 245)


def _label_box(img: Image.Image, b: TextBox, pad_ratio: float = 0.4) -> tuple[int, int, int, int]:
    pad_w, pad_h = int(b.w * pad_ratio), int(b.h * pad_ratio)
    x0, y0 = max(0, b.x - pad_w), max(0, b.y - pad_h)
    x1, y1 = min(img.width, b.x + b.w + pad_w), min(img.height, b.y + b.h + pad_h)
    return x0, y0, x1, y1


def _draw_label(img: Image.Image, b: TextBox, font_path: str) -> None:
    """原地绘制：背景色标签（盖住原文残影）+ 对比色文字（蒙版合成防溢出）。"""
    if not b.ru_text:
        return
    bg = _bg_color(img, b)
    x0, y0, x1, y1 = _label_box(img, b)
    ImageDraw.Draw(img).rectangle([x0, y0, x1 - 1, y1 - 1], fill=bg)
    layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = _fit_font(d, b.ru_text, x1 - x0, y1 - y0, font_path)
    tw = d.textlength(b.ru_text, font=f)
    asc, desc = f.getmetrics()
    d.text((max(0, (x1 - x0 - tw) // 2), max(0, (y1 - y0 - (asc + desc)) // 2)),
           b.ru_text, font=f, fill=_contrast_text_color(bg) + (255,))
    img.paste(layer, (x0, y0), layer)


def draw_translations(img: Image.Image, boxes: list[TextBox], font_path: str) -> Image.Image:
    out = img.convert("RGB").copy()
    for b in boxes:
        _draw_label(out, b, font_path)
    return out


def translate_image_bytes(data: bytes, boxes: list[TextBox], font_path: str) -> bytes:
    with Image.open(io.BytesIO(data)) as src:
        img = src.convert("RGB")
    erased = erase_boxes(img, boxes)
    out = draw_translations(erased, boxes, font_path)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()
