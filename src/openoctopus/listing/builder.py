def build_import_payload(
    title_ru: str,
    description_ru: str,
    offer_id: str,
    price_rub: float,
    category_id: int,
    attributes: list[dict],
    image_urls: list[str],
) -> dict:
    return {
        "items": [
            {
                "offer_id": offer_id,
                "name": title_ru[:200],
                "description": description_ru,
                "description_category_id": category_id,
                "price": str(price_rub),
                "currency_code": "RUB",
                "images": image_urls,
                "attributes": [
                    {
                        "complex_id": 0,
                        "id": int(a["id"]),
                        "values": (
                            [{"dictionary_value_id": a["dictionary_value_id"]}]
                            if a.get("dictionary_value_id")
                            else [{"value": a["value"]}]
                        ),
                    }
                    for a in attributes
                ],
            }
        ]
    }
