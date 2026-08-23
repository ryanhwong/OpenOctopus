from io import BytesIO

import numpy as np
from PIL import Image

from openoctopus.image.render import (
    draw_translations,
    erase_boxes,
    translate_image_bytes,
)
from openoctopus.models import TextBox

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def make_img() -> Image.Image:
    img = Image.new("RGB", (200, 100), (240, 240, 240))
    for x in range(20, 180):
        for y in range(40, 60):
            img.putpixel((x, y), (10, 10, 10))
    return img


def assert_outside_unchanged(before: Image.Image, after: Image.Image, box: TextBox) -> None:
    a = np.array(before.convert("RGB"))
    b = np.array(after.convert("RGB"))
    a[max(0, box.y):box.y + box.h, max(0, box.x):box.x + box.w] = 0
    b[max(0, box.y):box.y + box.h, max(0, box.x):box.x + box.w] = 0
    np.testing.assert_array_equal(a, b)


def test_erase_only_inside_box():
    base = make_img()
    box = TextBox(x=20, y=40, w=160, h=20, zh_text="", ru_text="")
    img = erase_boxes(base.copy(), [box])
    assert sum(img.getpixel((100, 50))) > 600
    assert_outside_unchanged(base, img, box)


def test_draw_translations_changes_box():
    base = make_img()
    box = TextBox(x=20, y=40, w=160, h=20, zh_text="保温杯", ru_text="Термос")
    erased = erase_boxes(base.copy(), [TextBox(x=20, y=40, w=160, h=20, zh_text="", ru_text="")])
    out = draw_translations(erased, [box], FONT_PATH)
    hist_a = erased.crop((20, 40, 180, 60)).tobytes()
    hist_b = out.crop((20, 40, 180, 60)).tobytes()
    assert hist_a != hist_b
    assert_outside_unchanged(erased, out, box)


def test_draw_translations_no_overflow_right():
    base = make_img()
    box = TextBox(x=168, y=40, w=24, h=20, zh_text="", ru_text="Термостермос")
    out = draw_translations(base.copy(), [box], FONT_PATH)
    assert_outside_unchanged(base, out, box)


def test_draw_translations_no_overflow_below():
    base = make_img()
    box = TextBox(x=30, y=56, w=100, h=4, zh_text="", ru_text="Термос")
    out = draw_translations(base.copy(), [box], FONT_PATH)
    assert_outside_unchanged(base, out, box)


def test_translate_image_bytes_roundtrip():
    buf = BytesIO()
    make_img().save(buf, "PNG")
    original = buf.getvalue()
    box = TextBox(x=20, y=40, w=160, h=20, zh_text="杯", ru_text="Чашка")
    data = translate_image_bytes(original, [box], FONT_PATH)
    assert Image.open(BytesIO(data)).size == (200, 100)
    assert data != original
    assert_outside_unchanged(Image.open(BytesIO(original)), Image.open(BytesIO(data)), box)
