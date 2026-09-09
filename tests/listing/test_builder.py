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
        ], model_name="Термос")
    assert [i["offer_id"] for i in items] == ["7-1", "7-2"]
    assert [i["price"] for i in items] == ["150", "160"]
    assert items[0]["images"] == ["https://c/r.png"]
    ids0 = [a["id"] for a in items[0]["attributes"]]
    ids1 = [a["id"] for a in items[1]["attributes"]]
    assert MERGE_ATTR_ID in ids0 and MERGE_ATTR_ID not in ids1
    assert items[0]["attributes"][-1] == {"complex_id": 0, "id": MERGE_ATTR_ID,
                                          "values": [{"value": "Термос"}]}
    # 变体颜色去重了基础同 id 属性
    assert ids1.count(85) == 1


def test_build_variant_items_dedupes_base_color():
    from openoctopus.listing.builder import build_variant_items

    base = [{"complex_id": 0, "id": 85, "values": [{"value": "旧颜色"}]}]
    items = build_variant_items(
        title_ru="T", description_ru="d", offer_id="7",
        category_id=42, type_id=99, base_attributes=base,
        variants=[{"suffix": "R", "price_rub": 10, "image_urls": [],
                   "color_attr_id": 85, "color_value": "Красный", "color_dict_id": None}],
        model_name="T")
    color_vals = [a for a in items[0]["attributes"] if a["id"] == 85]
    assert len(color_vals) == 1
    assert color_vals[0]["values"] == [{"value": "Красный"}]


def test_build_variant_items_dims():
    from openoctopus.listing.builder import build_variant_items

    items = build_variant_items(
        title_ru="T", description_ru="d", offer_id="7",
        category_id=42, type_id=99, base_attributes=[],
        variants=[{"suffix": "R", "price_rub": 10, "image_urls": [],
                   "color_attr_id": 0, "color_value": "R", "color_dict_id": None}],
        dims={"length": 100, "width": 50, "height": 20, "weight": 150})
    assert items[0]["weight"] == 150
    assert items[0]["weight_unit"] == "g"
    assert (items[0]["width"], items[0]["height"], items[0]["depth"]) == (50, 20, 100)
    assert items[0]["dimension_unit"] == "mm"


def test_build_variant_items_no_dims():
    from openoctopus.listing.builder import build_variant_items

    items = build_variant_items(
        title_ru="T", description_ru="d", offer_id="7",
        category_id=42, type_id=99, base_attributes=[],
        variants=[{"suffix": "R", "price_rub": 10, "image_urls": [],
                   "color_attr_id": 0, "color_value": "R", "color_dict_id": None}])
    assert "weight" not in items[0]
