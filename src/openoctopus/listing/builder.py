MERGE_ATTR_ID = 9048


def build_variant_items(title_ru: str, description_ru: str, offer_id: str,
                        category_id: int, type_id: int, base_attributes: list[dict],
                        variants: list[dict], currency_code: str = "RUB",
                        dims: dict | None = None) -> list[dict]:
    """多色变体 items：同名同类目，除颜色外属性一致 + 9048 合并属性。

    variants 每项: {suffix, price_rub, image_urls, color_attr_id,
                    color_value, color_dict_id|None}
    """
    items = []
    for i, v in enumerate(variants, 1):
        attrs = [dict(a) for a in base_attributes]
        if v.get("color_attr_id"):
            if v.get("color_dict_id") is not None:
                cv = [{"dictionary_value_id": v["color_dict_id"]}]
            else:
                cv = [{"value": v["color_value"]}]
            attrs.append({"complex_id": 0, "id": int(v["color_attr_id"]), "values": cv})
        if i == 1:
            attrs.append({"complex_id": 0, "id": MERGE_ATTR_ID, "values": [{"value": "да"}]})
        items.append({
            "offer_id": f"{offer_id}-{i}",
            "name": title_ru[:200],
            "description": description_ru,
            "description_category_id": category_id,
            "type_id": type_id,
            "price": str(v["price_rub"]),
            "currency_code": currency_code,
            "images": v["image_urls"],
            "attributes": attrs,
            **_dims_fields(dims),
        })
    return items


def _dims_fields(dims: dict | None) -> dict:
    if not dims or not all(dims.get(k) for k in ("length", "width", "height", "weight")):
        return {}
    return {"weight": dims["weight"], "weight_unit": "g",
            "width": dims["width"], "height": dims["height"], "depth": dims["length"],
            "dimension_unit": "mm"}
def build_import_payload(
    title_ru: str,
    description_ru: str,
    offer_id: str,
    price_rub: float,
    category_id: int,
    type_id: int,
    attributes: list[dict],
    image_urls: list[str],
    currency_code: str = "RUB",
    dims: dict | None = None,
) -> dict:
    return {
        "items": [
            {
                "offer_id": offer_id,
                "name": title_ru[:200],
                "description": description_ru,
            "description_category_id": category_id,
            "type_id": type_id,
            "price": str(price_rub),
            "currency_code": currency_code,
            "images": image_urls,
            **_dims_fields(dims),
            "attributes": [
                    {
                        "complex_id": 0,
                        "id": int(a["id"]),
                        "values": (
                            [{"dictionary_value_id": a["dictionary_value_id"]}]
                            if a.get("dictionary_value_id") is not None
                            else [{"value": a["value"]}]
                        ),
                    }
                    for a in attributes
                ],
            }
        ]
    }
