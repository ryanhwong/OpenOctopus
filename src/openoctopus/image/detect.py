import base64
import json

from openoctopus.models import TextBox

DETECT_PROMPT = (
    "Locate ALL Chinese text in this product image. For each region give integer "
    "bbox (x,y,w,h from top-left), the original zh_text and its Russian translation "
    "ru_text suited for e-commerce. Include prices as-is converted to format "
    '"Цена: <число> юаней". Respond strict JSON: {"boxes": [...]}'
)


async def detect_and_translate(client, model: str, image_bytes: bytes) -> list[TextBox]:
    b64 = base64.b64encode(image_bytes).decode()
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": DETECT_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    data = json.loads(resp.choices[0].message.content)
    return [TextBox(**b) for b in data.get("boxes", [])]
