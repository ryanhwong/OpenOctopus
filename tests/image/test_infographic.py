from io import BytesIO

from PIL import Image

FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def _jpeg():
    img = Image.new("RGB", (800, 800), (200, 120, 60))
    buf = BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def test_make_infographic_outputs_square_jpeg():
    from openoctopus.image.infographic import make_infographic

    out = make_infographic(_jpeg(), "Тестовый ремешок",
                           ["Строка 1", "Строка 2", "Строка 3"], FONT)
    img = Image.open(BytesIO(out))
    assert img.size == (1080, 1080)
    assert img.format == "JPEG"


def test_make_title_card_outputs_square_jpeg():
    from openoctopus.image.infographic import make_title_card

    out = make_title_card("Заголовок", ["а", "б"], FONT)
    img = Image.open(BytesIO(out))
    assert img.size == (1080, 1080)
    assert img.format == "JPEG"
