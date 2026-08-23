import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from openoctopus.models import TextBox


def _dominant_color(img: Image.Image, b: TextBox) -> tuple[int, int, int]:
    region = np.array(img.crop((b.x, b.y, b.x + b.w, b.y + b.h))).reshape(-1, 3)
    dark = region[region.sum(axis=1) < 380]
    px = dark if len(dark) else region
    return tuple(int(c) for c in px.mean(axis=0))


def erase_boxes(img: Image.Image, boxes: list[TextBox]) -> Image.Image:
    arr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    mask = np.zeros(arr.shape[:2], np.uint8)
    for b in boxes:
        mask[max(0, b.y):b.y + b.h, max(0, b.x):b.x + b.w] = 255
    if boxes:
        arr = cv2.inpaint(arr, mask, 5, cv2.INPAINT_TELEA)
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


def _render_box_text(
    b: TextBox, fill: tuple[int, int, int], font_path: str
) -> Image.Image:
    layer = Image.new("RGB", (b.w, b.h))
    d = ImageDraw.Draw(layer)
    f = _fit_font(d, b.ru_text, b.w, b.h, font_path)
    tw = int(d.textlength(b.ru_text, font=f))
    asc, desc = f.getmetrics()
    x = max(0, (b.w - tw) // 2)
    y = max(0, (b.h - (asc + desc)) // 2)
    d.text((x, y), b.ru_text, font=f, fill=fill)
    return layer


def _draw_translations(
    img: Image.Image,
    boxes: list[TextBox],
    font_path: str,
    colors: dict[int, tuple[int, int, int]],
) -> Image.Image:
    out = img.convert("RGB").copy()
    for i, b in enumerate(boxes):
        if not b.ru_text:
            continue
        out.paste(_render_box_text(b, colors[i], font_path), (b.x, b.y))
    return out


def draw_translations(img: Image.Image, boxes: list[TextBox], font_path: str) -> Image.Image:
    colors = {i: _dominant_color(img, b) for i, b in enumerate(boxes)}
    return _draw_translations(img, boxes, font_path, colors)


def translate_image_bytes(data: bytes, boxes: list[TextBox], font_path: str) -> bytes:
    with Image.open(io.BytesIO(data)) as src:
        img = src.convert("RGB")
    colors = {i: _dominant_color(img, b) for i, b in enumerate(boxes)}
    erased = erase_boxes(img, boxes)
    out = _draw_translations(erased, boxes, font_path, colors)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()
