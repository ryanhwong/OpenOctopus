import json

from openoctopus.image.detect import detect_and_translate


class FakeVisionCompletions:
    async def create(self, **kw):
        boxes = {"boxes": [{"x": 1, "y": 2, "w": 3, "h": 4, "zh_text": "保温", "ru_text": "Термос"}]}
        msg = type("M", (), {"content": json.dumps(boxes)})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


class FakeChat:
    def __init__(self):
        self.completions = FakeVisionCompletions()


class FakeClient:
    def __init__(self):
        self.chat = FakeChat()


async def test_detect_returns_boxes():
    boxes = await detect_and_translate(FakeClient(), "m", b"img")
    assert boxes[0].ru_text == "Термос"
    assert (boxes[0].x, boxes[0].w) == (1, 3)
