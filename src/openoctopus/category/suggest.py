import json

PICK_PROMPT = (
    "Given a product description and candidate Ozon categories, pick the best "
    'category_id. Respond strict JSON: {"category_id": "<id>"}'
)

ATTRS_PROMPT = (
    "Map this product to the given Ozon attribute schema values in Russian. "
    'Respond strict JSON: {"attributes": [{"id": int, "value": str, '
    '"dictionary_value_id": int|null}]}'
)


async def pick_category(client, model, candidates, raw, translated) -> str:
    user = json.dumps({"product": translated.model_dump() if translated else {},
                       "candidates": candidates[:300]}, ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": PICK_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.0)
    return str(json.loads(resp.choices[0].message.content)["category_id"])


async def fill_attributes(client, model, schema_items, category_id, raw, translated) -> list[dict]:
    user = json.dumps({"schema": schema_items,
                       "product_zh": raw.model_dump() if raw else {},
                       "product_ru": translated.model_dump() if translated else {}},
                      ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": ATTRS_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.0)
    return json.loads(resp.choices[0].message.content)["attributes"]
