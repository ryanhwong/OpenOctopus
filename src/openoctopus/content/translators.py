import json

from openoctopus.models import RawProduct, TranslatedContent

SYSTEM_PROMPT = (
    "You localize Chinese e-commerce listings for the Russian marketplace Ozon. "
    "Translate to natural Russian buyer-facing copy. Rewrite the title so the most "
    "searchable keywords come first (max 120 chars). Keep bullet points concise. "
    'Respond with strict JSON: {"title_ru": str, "bullets_ru": [str], "description_ru": str}'
)


class LLMContentTranslator:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    async def translate(self, raw: RawProduct) -> TranslatedContent:
        user = json.dumps({
            "title": raw.title_zh,
            "bullets": raw.bullets_zh,
            "description": raw.description_zh,
            "sku_options": [{k: v for k, v in s.props.items()} for s in raw.skus],
        }, ensure_ascii=False)
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content)
        return TranslatedContent(**data, model=self.model)
