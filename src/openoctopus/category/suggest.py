import json

from openoctopus.llm_json import first_content, parse_json

PICK_PROMPT = (
    "Given a product description and candidate Ozon leaf types, pick the best one. "
    "Candidates are leaf types only; their ids look like "
    '"<description_category_id>:<type_id>". Copy one id VERBATIM from candidates; '
    'it MUST contain a ":" character. Respond strict JSON: {"category_id": "<id>"}'
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
    return str(parse_json(first_content(resp))["category_id"])


OPTION_PROMPT = (
    "Translate these Chinese e-commerce product option names (colors, sizes) "
    "to concise Russian terms. "
    'Respond strict JSON: {"options": [{"zh": str, "ru": str}]}'
)

MATCH_PROMPT = (
    "Match each Russian product option to the best dictionary value id. "
    'Respond strict JSON: {"matches": [{"ru": str, "dictionary_value_id": int|null}]}'
)


async def translate_options(client, model, options: list[str]) -> dict[str, str]:
    if not options:
        return {}
    user = json.dumps({"options": options}, ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": OPTION_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.0)
    return {o["zh"]: o["ru"] for o in
            parse_json(first_content(resp)).get("options", [])
            if isinstance(o, dict) and "zh" in o and "ru" in o}


async def match_option_values(client, model, options_ru: list[str],
                              dict_values: list[dict]) -> dict[str, int | None]:
    if not options_ru:
        return {}
    user = json.dumps({"options": options_ru,
                       "dictionary": [{"id": v.get("id"), "value": v.get("value")}
                                      for v in dict_values[:100]]}, ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": MATCH_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.0)
    return {m["ru"]: m.get("dictionary_value_id") for m in
            parse_json(first_content(resp)).get("matches", [])
            if isinstance(m, dict) and "ru" in m}
async def fill_attributes(client, model, schema_items, raw, translated) -> list[dict]:
    user = json.dumps({"schema": schema_items,
                       "product_zh": raw.model_dump() if raw else {},
                       "product_ru": translated.model_dump() if translated else {}},
                      ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": ATTRS_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.0)
    attrs = parse_json(first_content(resp))["attributes"]
    return [a for a in attrs if isinstance(a, dict) and "id" in a]
