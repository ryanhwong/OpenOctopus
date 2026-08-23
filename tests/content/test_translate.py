import json

from openoctopus.content.translators import LLMContentTranslator
from openoctopus.models import RawProduct


class FakeCompletions:
    async def create(self, **kw):
        self.kw = kw
        content = json.dumps({"title_ru": "Термос из нержавеющей стали 304",
                              "bullets_ru": ["Большой объём"],
                              "description_ru": "Портативный термос."})
        msg = type("M", (), {"content": content})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


async def test_translate():
    c = LLMContentTranslator(FakeClient(), model="test-model")
    raw = RawProduct(source_url="u", platform="1688", title_zh="不锈钢保温杯",
                     bullets_zh=["大容量"], description_zh="便携水杯")
    out = await c.translate(raw)
    assert out.title_ru.startswith("Термос")
    assert out.model == "test-model"


def test_prompt_mentions_ozon():
    from openoctopus.content.translators import SYSTEM_PROMPT
    assert "Ozon" in SYSTEM_PROMPT and "JSON" in SYSTEM_PROMPT
