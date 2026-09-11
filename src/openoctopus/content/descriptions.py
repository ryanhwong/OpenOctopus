"""描述工程：LLM 结构化重写（卖点列表 + 收尾）。"""

import json

from openoctopus.llm_json import first_content, parse_json

DESC_PROMPT = (
    "Rewrite this Ozon.ru product description in natural Russian. Structure:\n"
    "1) short intro (1-2 sentences);\n"
    "2) a line 'Преимущества:' followed by 3-5 bullet lines starting with '• ';\n"
    "3) one closing sentence.\n"
    "No HTML, no emojis, no links, no seller/contact info, max 900 characters. "
    "Use only the given facts, do not invent specs.\n"
    'Respond strict JSON: {"description": str}'
)


async def improve_description(client, model, *, title: str, current: str,
                              bullets: str = "") -> str:
    user = json.dumps({"title_ru": title, "description_ru": current,
                       "bullets_ru": bullets}, ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": DESC_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.4)
    data = parse_json(first_content(resp))
    return str(data.get("description") or "").strip()[:1200]
