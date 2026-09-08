import json
from pathlib import Path

from openoctopus.listing.builder import build_import_payload

GOLDEN = json.loads((Path(__file__).parent.parent / "fixtures" / "golden_import.json").read_text())


def test_build_matches_golden():
    payload = build_import_payload(
        title_ru="Термос из нержавеющей стали",
        description_ru="Портативный термос.",
        offer_id="oo-1",
        price_rub=150.0,
        category_id=42,
        type_id=99,
        attributes=[{"id": 85, "value": "Сталь"},
                    {"id": 90, "value": "", "dictionary_value_id": 123}],
        image_urls=["https://cdn.example.com/a.png"],
    )
    assert payload == GOLDEN


def test_name_truncated():
    p = build_import_payload("Б" * 500, "d", "of", 10.0, 1, 2, [], [])
    assert len(p["items"][0]["name"]) == 200


def test_build_variant_items():
    from openoctopus.listing.builder import MERGE_ATTR_ID, build_variant_items

    items = build_variant_items(
        title_ru="Термос", description_ru="d", offer_id="7",
        category_id=42, type_id=99, base_attributes=[{"complex_id": 0, "id": 1, "values": [{"value": "x"}]}],
        variants=[
            {"suffix": "Красный", "price_rub": 150, "image_urls": ["https://c/r.png"],
             "color_attr_id": 85, "color_value": "Красный", "color_dict_id": 123},
            {"suffix": "Синий", "price_rub": 160, "image_urls": ["https://c/b.png"],
             "color_attr_id": 85, "color_value": "Синий", "color_dict_id": None},
        ])
    assert [i["offer_id"] for i in items] == ["7-1", "7-2"]
    assert [i["price"] for i in items] == ["150", "160"]
    assert items[0]["images"] == ["https://c/r.png"]
    for i in items:
        ids = [a["id"] for a in i["attributes"]]
        assert MERGE_ATTR_ID in ids and 1 in ids
    assert items[0]["attributes"][1] == {"complex_id": 0, "id": 85,
                                         "values": [{"dictionary_value_id": 123}]}
    assert items[1]["attributes"][1] == {"complex_id": 0, "id": 85,
                                         "values": [{"value": "Синий"}]}
