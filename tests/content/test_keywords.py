from types import SimpleNamespace


async def test_extract_keywords():
    from openoctopus.content.keywords import extract_keywords

    payload = ('{"keywords": ["ремешок для apple watch", "браслет для часов",'
               ' "нейлоновый ремешок"]}')

    async def create(**_kw):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    out = await extract_keywords(client, "m", ["Some competitor title"])
    assert out[0] == "ремешок для apple watch"
    assert len(out) == 3


async def test_extract_keywords_empty_titles():
    from openoctopus.content.keywords import extract_keywords

    assert await extract_keywords(None, "m", []) == []
