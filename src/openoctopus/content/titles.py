"""Ozon 标题工程：结构化生成候选标题 + 质检。"""

import json
import re

from openoctopus.llm_json import first_content, parse_json

BRANDS = ("apple", "samsung", "xiaomi", "huawei", "galaxy", "iwatch")

TITLE_PROMPT = (
    "You are an Ozon.ru listing optimizer. Write Russian product titles for a marketplace card.\n"
    "Rules:\n"
    "- Structure: [material/key feature] + [product type] + [compatibility/purpose] + [key benefit]\n"
    "- Use the words Russian buyers actually search, 3-5 keywords naturally placed; NEVER stuff keywords\n"
    "- Max 150 characters, no period at the end, no ALL CAPS words, no emoji, no '!!!'\n"
    "- Never claim to be an official brand product; compatibility wording like 'для Apple Watch' is fine\n"
    "- No superlatives like 'лучший', '№1', 'хит продаж'\n"
    'Respond strict JSON: {"titles": [{"style": "seo", "text": "..."}, '
    '{"style": "short", "text": "..."}, {"style": "benefit", "text": "..."}]}\n'
    "seo = maximum search coverage; short = concise and clean; benefit = main advantage first."
)

STYLE_LABELS = {"seo": "SEO 覆盖型", "short": "简洁型", "benefit": "卖点型"}

EMOJI_RE = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\u2b00-\u2bff]")


def material_ru(title_zh: str) -> str:
    zh = title_zh or ""
    for keys, label in ((("尼龙", "尼龍", "编织", "編織"), "нейлоновый"),
                        (("硅胶", "矽胶", "硅膠"), "силиконовый"),
                        (("皮革", "真皮", "pu皮"), "кожаный"),
                        (("不锈钢", "金属"), "металлический")):
        if any(k in zh for k in keys):
            return label
    return ""


def compat_ru(title_zh: str) -> str:
    zh = (title_zh or "").lower()
    if any(k in zh for k in ("苹果", "apple", "iwatch", "watch", "手表")):
        return "для Apple Watch"
    return ""


def template_titles(*, type_ru: str, material: str, compat: str,
                    feature: str = "") -> list[dict]:
    """规则兜底：无 LLM 时也能产出可用标题。"""
    t = (type_ru or "ремешок").strip()
    mat = (material + " ") if material else ""
    tail = (feature or "эластичный, магнитная застёжка").strip(", ")
    base = f"{mat}{t} {compat}".strip()
    seo = f"{base}, {tail}" if tail else base
    benefit = f"{compat} — {base.replace(compat, '').strip()}, {tail}".strip(" —,")
    return [{"style": "seo", "text": re.sub(r"\s+", " ", seo)[:150]},
            {"style": "short", "text": re.sub(r"\s+", " ", base)[:150]},
            {"style": "benefit", "text": re.sub(r"\s+", " ", benefit)[:150]}]


async def generate_titles(client, model, *, title_zh: str, title_ru: str, desc_ru: str,
                          compat: str = "", type_ru: str = "",
                          keywords: list[str] | None = None) -> list[dict]:
    """LLM 生成 3 个风格候选；不足 2 个时抛错由调用方兜底。"""
    user = json.dumps({
        "chinese_title": title_zh,
        "draft_title_ru": title_ru,
        "description_ru": (desc_ru or "")[:600],
        "material_ru": material_ru(title_zh),
        "product_type_ru": type_ru,
        "compatibility": compat,
        "buyer_keywords": keywords or [],
    }, ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": TITLE_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.4)
    data = parse_json(first_content(resp))
    out = []
    for t in data.get("titles", []):
        if isinstance(t, dict) and str(t.get("text") or "").strip():
            out.append({"style": str(t.get("style") or "seo"),
                        "text": str(t["text"]).strip()[:200]})
    if len(out) < 2:
        raise ValueError("LLM 返回的标题候选不足")
    return out[:3]


def check_title(ru: str) -> list[str]:
    """标题质检，返回中文警告列表（空=通过）。"""
    ru = (ru or "").strip()
    if not ru:
        return ["标题为空"]
    warns = []
    if len(ru) > 150:
        warns.append(f"过长（{len(ru)} 字符，建议 ≤150）")
    if len(ru) < 25:
        warns.append(f"过短（{len(ru)} 字符，建议 ≥25）")
    if ru.endswith("."):
        warns.append("结尾有句号，Ozon 标题一般不带")
    if re.search(r"!{2,}", ru):
        warns.append("含连续感叹号")
    if EMOJI_RE.search(ru):
        warns.append("含 emoji，Ozon 标题不允许")
    words = re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", ru.lower())
    over = [w for w in dict.fromkeys(words) if words.count(w) > 2]
    if over:
        warns.append(f"重复词过多：{', '.join(over[:3])}")
    caps = re.findall(r"\b[А-ЯЁA-Z]{4,}\b", ru)
    if caps:
        warns.append(f"全大写词：{', '.join(caps[:3])}")
    if words and any(b in words[0] for b in BRANDS):
        warns.append("以品牌词开头，疑似冒充官方，建议「ремешок для …」结构")
    for bad in ("лучший", "самый лучший", "№1", "no.1", "хит продаж", "дешевый"):
        if bad in ru.lower():
            warns.append(f"含广告违禁词「{bad}」")
    return warns


def style_label(style: str) -> str:
    return STYLE_LABELS.get(style, style)
