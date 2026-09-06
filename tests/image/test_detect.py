import json

from openoctopus.image.detect import _normalize_box, detect_and_translate


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


def test_normalize_bbox_array_form():
    b = _normalize_box({"bbox": [29, 41, 64, 23], "zh_text": "杯", "ru_text": "Чашка"})
    assert (b.x, b.y, b.w, b.h) == (29, 41, 64, 23)
    assert b.ru_text == "Чашка"


def test_normalize_min_max_form():
    b = _normalize_box({"x_min": 10, "y_min": 20, "x_max": 50, "y_max": 60,
                        "zh_text": "", "ru_text": ""})
    assert (b.x, b.y, b.w, b.h) == (10, 20, 40, 40)
