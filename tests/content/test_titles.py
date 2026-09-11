from types import SimpleNamespace


def test_check_title_ok():
    from openoctopus.content.titles import check_title

    assert check_title("Нейлоновый магнитный ремешок для Apple Watch, эластичный") == []


def test_check_title_flags():
    from openoctopus.content.titles import check_title

    joined = " ".join(check_title("Apple ЛУЧШИЙ ремешок ремешок ремешок ремешок!!! " + "x" * 160))
    assert "过长" in joined
    assert "全大写" in joined
    assert "感叹号" in joined
    assert "重复词过多" in joined
    assert "冒充官方" in joined
    assert "违禁词" in joined
    assert check_title("") == ["标题为空"]


def test_template_titles():
    from openoctopus.content.titles import template_titles

    cands = template_titles(type_ru="Ремешок для умных часов", material="нейлоновый",
                            compat="для Apple Watch", feature="эластичный")
    assert len(cands) == 3
    assert {c["style"] for c in cands} == {"seo", "short", "benefit"}
    assert "нейлоновый" in cands[0]["text"].lower()
    assert "Apple Watch" in cands[0]["text"]
    assert all(len(c["text"]) <= 150 for c in cands)


def test_material_and_compat_ru():
    from openoctopus.content.titles import compat_ru, material_ru

    assert material_ru("尼龙编织表带") == "нейлоновый"
    assert material_ru("硅胶表带") == "силиконовый"
    assert material_ru("保温杯") == ""
    assert compat_ru("适用苹果手表") == "для Apple Watch"
    assert compat_ru("保温杯") == ""


async def test_generate_titles_llm():
    from openoctopus.content.titles import generate_titles

    payload = ('{"titles":[{"style":"seo","text":"Ремешок нейлоновый для часов"},'
               '{"style":"short","text":"Ремешок нейлоновый"},'
               '{"style":"benefit","text":"Магнитный ремешок"}]}')

    async def create(**_kw):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    out = await generate_titles(client, "m", title_zh="表带", title_ru="draft", desc_ru="d")
    assert [t["style"] for t in out] == ["seo", "short", "benefit"]


async def test_generate_titles_llm_too_few_raises():
    import pytest

    from openoctopus.content.titles import generate_titles

    async def create(**_kw):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"titles":[]}'))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(ValueError):
        await generate_titles(client, "m", title_zh="表带", title_ru="draft", desc_ru="d")
