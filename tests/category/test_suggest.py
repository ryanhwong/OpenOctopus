import json

from openoctopus.category.suggest import fill_attributes, pick_category


class FakeMsg:
    def __init__(self, c):
        self.content = c


class FakeResp:
    def __init__(self, c):
        self.choices = [type("C", (), {"message": FakeMsg(c)})()]


class SeqLLM:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw["messages"])
        return FakeResp(self.replies[len(self.calls) - 1])


class Wrap:
    def __init__(self, comp):
        self.chat = type("Chat", (), {"completions": comp})()


async def test_pick_and_fill():
    llm = SeqLLM([json.dumps({"category_id": "42"}),
                  json.dumps({"attributes": [{"id": 85, "value": "Термос"}]})])
    cat_id = await pick_category(Wrap(llm), "m", [], None, None)
    assert cat_id == "42"
    attrs = await fill_attributes(Wrap(llm), "m", None, None, None)
    assert attrs == [{"id": 85, "value": "Термос"}]
