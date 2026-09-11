"""首图信息图 / 视频标题卡：PIL 叠字渲染。"""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

BG = (15, 23, 42, 170)
FG = (255, 255, 255, 255)
FG2 = (226, 232, 240, 255)


def _fonts(font_path: str, title_size: int = 46, line_size: int = 34):
    try:
        return (ImageFont.truetype(font_path, title_size),
                ImageFont.truetype(font_path, line_size))
    except Exception:  # noqa: BLE001
        f = ImageFont.load_default()
        return f, f


def make_infographic(image_bytes: bytes, title: str, lines: list[str],
                     font_path: str) -> bytes:
    """主图底部叠加半透明卖点带，输出 JPEG 字节。"""
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    if w != 1080:
        img = img.resize((1080, max(1, int(h * 1080 / w))))
        w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    band_h = int(h * 0.34) if h > 700 else int(h * 0.42)
    y0 = h - band_h
    draw.rectangle([0, y0, w, h], fill=BG)
    f_title, f_line = _fonts(font_path)
    pad = max(24, int(w * 0.04))
    draw.text((pad, y0 + 22), (title or "")[:38], font=f_title, fill=FG)
    ty = y0 + 22 + 62
    for ln in [line for line in lines if line][:3]:
        draw.text((pad, ty), "• " + ln[:46], font=f_line, fill=FG2)
        ty += 48
        if ty > h - 20:
            break
    out = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    buf = BytesIO()
    out.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def make_title_card(title: str, lines: list[str], font_path: str) -> bytes:
    """视频标题卡（深底白字），输出 JPEG 字节。"""
    img = Image.new("RGB", (1080, 1080), (15, 23, 42))
    draw = ImageDraw.Draw(img)
    f_title, f_line = _fonts(font_path, title_size=56, line_size=38)
    pad = 80
    draw.text((pad, 380), (title or "")[:34], font=f_title, fill=FG)
    ty = 470
    for ln in [line for line in lines if line][:3]:
        draw.text((pad, ty), "• " + ln[:40], font=f_line, fill=FG2)
        ty += 56
    buf = BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()
