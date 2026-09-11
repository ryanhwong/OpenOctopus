from types import SimpleNamespace


async def test_improve_description_llm():
    from openoctopus.content.descriptions import improve_description

    payload = '{"description": "Интро.\\nПреимущества:\\n• Один\\n• Два\\nФинал."}'

    async def create(**_kw):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    out = await improve_description(client, "m", title="T", current="old", bullets="b1")
    assert "Преимущества" in out
