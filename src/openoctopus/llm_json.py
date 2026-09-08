"""LLM JSON 输出解析：免费模型经常无视 response_format，用 ```json 围栏包裹。"""

import json
import re


def first_content(resp) -> str:
    """取首个 choice 的文本；上游过载常回 choices=null/空，必须转成明错以便重试。"""
    choices = getattr(resp, "choices", None)
    if not choices:
        raise ValueError("LLM returned no choices (provider overloaded?), retry later")
    content = choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM returned empty content, retry later")
    return content


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError(f"LLM returned non-object JSON: {text[:150]!r}")
    return data
