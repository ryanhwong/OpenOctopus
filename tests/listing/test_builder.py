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
        attributes=[{"id": 85, "value": "Сталь"},
                    {"id": 90, "value": "", "dictionary_value_id": 123}],
        image_urls=["https://cdn.example.com/a.png"],
    )
    assert payload == GOLDEN


def test_name_truncated():
    p = build_import_payload("Б" * 500, "d", "of", 10.0, 1, [], [])
    assert len(p["items"][0]["name"]) == 200
