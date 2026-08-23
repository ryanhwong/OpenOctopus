from io import BytesIO

from PIL import Image

from openoctopus.image.render import (
    draw_translations,
    erase_boxes,
    translate_image_bytes,
)
from openoctopus.models import TextBox


def make_img() -> Image.Image:
    img = Image.new("RGB", (200, 100), (240, 240, 240))
    for x in range(20, 180):
        for y in range(40, 60):
            img.putpixel((x, y), (10, 10, 10))
    return img


def test_erase_only_inside_box():
    img = erase_boxes(make_img(), [TextBox(x=20, y=40, w=160, h=20, zh_text="", ru_text="")])
    assert sum(img.getpixel((100, 50))) > 600
    assert sum(img.getpixel((10, 10))) == 720


def test_draw_translations_changes_box():
    base = make_img()
    erased = erase_boxes(base.copy(), [TextBox(x=20, y=40, w=160, h=20, zh_text="", ru_text="")])
    out = draw_translations(erased, [TextBox(x=20, y=40, w=160, h=20, zh_text="保温杯", ru_text="Термос")],
                            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    hist_a = erased.crop((20, 40, 180, 60)).tobytes()
    hist_b = out.crop((20, 40, 180, 60)).tobytes()
    assert hist_a != hist_b


def test_translate_image_bytes_roundtrip():
    buf = BytesIO()
    make_img().save(buf, "PNG")
    data = translate_image_bytes(buf.getvalue(),
                                 [TextBox(x=20, y=40, w=160, h=20, zh_text="杯", ru_text="Чашка")],
                                 "/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    assert Image.open(BytesIO(data)).size == (200, 100)
