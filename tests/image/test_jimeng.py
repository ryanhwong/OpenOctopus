import json

import httpx

from openoctopus.image.jimeng import JimengEditAdapter, build_edit_prompt
from openoctopus.models import TextBox


def test_build_edit_prompt():
    boxes = [TextBox(x=1, y=1, w=2, h=2, zh_text="星光色", ru_text="Звёздный"),
             TextBox(x=5, y=5, w=2, h=2, zh_text="CLOUDHIS", ru_text="")]
    p = build_edit_prompt(boxes)
    assert "星光色->Звёздный" in p
    assert "CLOUDHIS" in p
    assert "exactly the same" in p


class FakeCompletions:
    def __init__(self, boxes):
        self._boxes = boxes

    async def create(self, **kw):
        msg = type("M", (), {"content": json.dumps({"boxes": self._boxes})})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


def _fake_llm(boxes):
    comp = FakeCompletions(boxes)
    return type("Client", (), {"chat": type("Chat", (), {"completions": comp})()})()


class FakeStorage:
    def __init__(self):
        self.put_called = False

    def put(self, key, data, mime="image/png"):
        self.put_called = True
        return "https://cdn.example.com/j.png"


class FakeVLM:
    def __init__(self):
        self.called = False

    async def translate(self, url, hint):
        self.called = True
        return "https://cdn.example.com/vlm.png"


def _adapter(handler, boxes, **kw):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = FakeStorage()
    vlm = FakeVLM()
    ad = JimengEditAdapter(http, "sess", "http://x", "jimeng-4.5",
                           _fake_llm(boxes), "m", storage,
                           fallback_translator=vlm, **kw)
    return ad, storage, vlm


async def test_happy_path_uploads_to_r2():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/images/generations":
            body = json.loads(request.content)
            assert body["images"] == ["https://img/a.jpg"]
            assert "星光色" in body["prompt"]
            assert request.headers["authorization"] == "Bearer sess"
            return httpx.Response(200, json={"data": [{"url": "https://jimeng/x.png"}]})
        return httpx.Response(200, content=b"imgbytes")

    boxes = [{"x": 1, "y": 1, "w": 2, "h": 2, "zh_text": "星光色", "ru_text": "RU"}]
    ad, storage, vlm = _adapter(handler, boxes)
    out = await ad.translate("https://img/a.jpg", "hint")
    assert out == "https://cdn.example.com/j.png"
    assert storage.put_called and not vlm.called


async def test_no_boxes_returns_original():
    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request.url.path)
        return httpx.Response(200, content=b"imgbytes")

    ad, _, vlm = _adapter(handler, [])
    assert await ad.translate("https://img/a.jpg", "hint") == "https://img/a.jpg"
    assert not any("generations" in p for p in called) and not vlm.called


async def test_sidecar_error_falls_back_to_vlm():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/images/generations":
            return httpx.Response(500, json={"error": "busy"})
        return httpx.Response(200, content=b"imgbytes")

    boxes = [{"x": 1, "y": 1, "w": 2, "h": 2, "zh_text": "a", "ru_text": "b"}]
    ad, storage, vlm = _adapter(handler, boxes)
    assert await ad.translate("https://img/a.jpg", "hint") == "https://cdn.example.com/vlm.png"
    assert vlm.called and not storage.put_called
