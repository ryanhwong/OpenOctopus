import json

from openoctopus.image.pipeline import VlmPipelineTranslator


class FakeVisionCompletions:
    def __init__(self, boxes):
        self._boxes = boxes

    async def create(self, **kw):
        payload = {"boxes": self._boxes}
        msg = type("M", (), {"content": json.dumps(payload)})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


class FakeChat:
    def __init__(self, boxes):
        self.completions = FakeVisionCompletions(boxes)


class FakeClient:
    def __init__(self, boxes=None):
        self.chat = FakeChat(boxes or [])


class FakeResp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class FakeHttp:
    def __init__(self, content):
        self.content = content

    async def get(self, url):
        return FakeResp(self.content)

    async def aclose(self):
        return None


class FakeStorage:
    def __init__(self):
        self.put_called = False
        self.saved = None

    def put(self, key, data, mime="image/png"):
        self.put_called = True
        self.saved = (key, data, mime)
        return "https://cdn.example.com/out.png"


def fake_render(data, boxes, font_path):
    return b"rendered-bytes"


async def test_translate_returns_original_url_when_no_boxes():
    tr = VlmPipelineTranslator(
        FakeClient([]), "m", FakeStorage(), "/fonts/x.ttf",
        http=FakeHttp(b"img"),
    )
    result = await tr.translate("https://example.com/a.png", "hint")
    assert result == "https://example.com/a.png"


async def test_translate_returns_original_url_when_storage_none():
    tr = VlmPipelineTranslator(
        FakeClient([{"x": 1, "y": 2, "w": 3, "h": 4, "zh_text": "保", "ru_text": "Термос"}]),
        "m", None, "/fonts/x.ttf",
        http=FakeHttp(b"img"),
    )
    result = await tr.translate("https://example.com/a.png", "hint")
    assert result == "https://example.com/a.png"


async def test_translate_happy_path_returns_public_url_and_put_called():
    storage = FakeStorage()
    tr = VlmPipelineTranslator(
        FakeClient([{"x": 1, "y": 2, "w": 3, "h": 4, "zh_text": "保", "ru_text": "Термос"}]),
        "m", storage, "/fonts/x.ttf",
        http=FakeHttp(b"img"),
        render=fake_render,
    )
    result = await tr.translate("https://example.com/a.png", "hint")
    assert result == "https://cdn.example.com/out.png"
    assert storage.put_called is True
    key, data, _ = storage.saved
    assert key.startswith("hint-")
    assert key.endswith(".png")
    assert data == b"rendered-bytes"
