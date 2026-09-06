import base64

from openoctopus.llm_json import parse_json
from openoctopus.models import TextBox

DETECT_PROMPT = (
    "Locate ALL text in this product image, including English brand logos, "
    "watermarks and corner labels — not only Chinese. For each region respond with "
    'an object {"x": int, "y": int, "w": int, "h": int, "zh_text": str, "ru_text": str} '
    "where x,y,w,h are integers from the top-left corner. "
    "For Chinese text, ru_text is the Russian translation suited for e-commerce "
    '(prices as "Цена: <число> юаней"). '
    "For NON-Chinese text (English logos etc.), set ru_text to empty string — "
    "it will be erased and not redrawn. Be exhaustive, include small text. "
    "Sweep all four corners and image edges for small logos - these are most often missed. "
    'Respond strict JSON: {"boxes": [...]}'
)


def _normalize_box(b: dict) -> TextBox:
    if isinstance(b.get("bbox"), (list, tuple)) and len(b["bbox"]) == 4:
        x, y, w, h = (int(v) for v in b["bbox"])
        return TextBox(x=x, y=y, w=w, h=h,
                       zh_text=b.get("zh_text", ""), ru_text=b.get("ru_text", ""))
    if all(k in b for k in ("x_min", "y_min", "x_max", "y_max")):
        x0, y0, x1, y1 = (int(b[k]) for k in ("x_min", "y_min", "x_max", "y_max"))
        return TextBox(x=x0, y=y0, w=max(0, x1 - x0), h=max(0, y1 - y0),
                       zh_text=b.get("zh_text", ""), ru_text=b.get("ru_text", ""))
    return TextBox(**b)


async def detect_and_translate(client, model: str, image_bytes: bytes,
                               prompt: str = DETECT_PROMPT) -> list[TextBox]:
    b64 = base64.b64encode(image_bytes).decode()
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    data = parse_json(resp.choices[0].message.content)
    return [_normalize_box(b) for b in data.get("boxes", [])]


LEFTOVER_PROMPT = (
    "Find any REMAINING Chinese text or English brand logos/watermarks in this image. "
    "IGNORE all Russian (Cyrillic) text - it is correct and must stay. "
    "For each leftover region respond with an object "
    '{"x": int, "y": int, "w": int, "h": int}. '
    "Be exhaustive, check corners and edges. "
    'Respond strict JSON: {"boxes": [...]}'
)
