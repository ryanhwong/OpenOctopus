import json


def test_rich_content_valid_json():
    from openoctopus.listing.enrich import build_rich_content

    raw = build_rich_content("Термос", "Первая строка\nВторая строка",
                             ["https://x/1.png", "https://x/2.png", "https://x/3.png"])
    d = json.loads(raw)
    assert d["version"] == 0.3
    widget = d["content"][0]
    assert widget["widgetName"] == "raShowcase"
    assert len(widget["blocks"]) == 3
    assert widget["blocks"][0]["img"]["src"] == "https://x/1.png"


def test_rich_content_too_few_images():
    from openoctopus.listing.enrich import build_rich_content

    assert build_rich_content("T", "d", ["https://x/1.png"]) == ""
    assert build_rich_content("T", "d", []) == ""


def test_extra_attributes_key_ids():
    from openoctopus.listing.enrich import build_extra_attributes

    attrs = build_extra_attributes(
        description_ru="текст " * 60, title_ru="Термос", weight_g=50,
        length_mm=120, width_mm=120, height_mm=50, material="textile",
        video_url="https://v/x.mp4", rich_content="{}", hashtags="#а")
    ids = [a["id"] for a in attrs]
    for aid in (4191, 4383, 4382, 4389, 7978, 10400, 22896, 23489,
                11254, 21841, 21845, 23171):
        assert aid in ids
    by_id = {a["id"]: a for a in attrs}
    assert by_id[7978]["values"][0]["dictionary_value_id"] == 43106
    assert by_id[21841]["values"][0]["value"] == "https://v/x.mp4"


def test_extra_attributes_silicone_dict():
    from openoctopus.listing.enrich import build_extra_attributes

    attrs = build_extra_attributes(
        description_ru="d", title_ru="T", weight_g=None,
        length_mm=None, width_mm=None, height_mm=None, material="silicone")
    by_id = {a["id"]: a for a in attrs}
    assert by_id[7978]["values"][0]["dictionary_value_id"] == 43105
    assert 4383 not in by_id


def test_safe_hashtags_filters_brands():
    from openoctopus.listing.enrich import safe_hashtags

    tags = safe_hashtags("applewatch", "ремешок", "iwatch", "силикон")
    assert "#ремешок" in tags
    assert "#силикон" in tags
    assert "apple" not in tags.lower().replace("#", "")


def test_slideshow_requires_images():
    from openoctopus.image.video import make_slideshow

    assert make_slideshow([]) == b""
    assert make_slideshow(["https://x/1.png"]) == b""


def test_parse_and_rebuild_roundtrip():
    from openoctopus.listing.enrich import (
        build_rich_content,
        build_rich_content_from_blocks,
        parse_rich_content,
    )

    raw = build_rich_content("Термос", "Первая строка\nВторая строка",
                             ["https://x/1.png", "https://x/2.png"])
    blocks = parse_rich_content(raw)
    assert len(blocks) == 2
    assert blocks[0]["img"] == "https://x/1.png"
    assert blocks[0]["title"] == "Термос"
    assert blocks[0]["text"] == "Первая строка"
    assert blocks[1]["text"] == "Вторая строка"

    edited = [dict(blocks[0], title="Новый заголовок"), blocks[1]]
    rebuilt = build_rich_content_from_blocks(edited)
    again = parse_rich_content(rebuilt)
    assert again[0]["title"] == "Новый заголовок"
    assert again[0]["img"] == "https://x/1.png"


def test_parse_rich_content_tolerates_garbage():
    from openoctopus.listing.enrich import (
        build_rich_content_from_blocks,
        parse_rich_content,
    )

    assert parse_rich_content("") == []
    assert parse_rich_content("not json") == []
    assert parse_rich_content('{"version": 0.3, "content": []}') == []
    assert build_rich_content_from_blocks([]) == ""
    assert build_rich_content_from_blocks([{"img": "", "title": "x", "text": "y"}]) == ""
