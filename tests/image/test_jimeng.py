import json

import httpx

from openoctopus.image.jimeng import JimengEditAdapter, build_edit_prompt


def test_build_edit_prompt():
    p = build_edit_prompt({"星光色": "Звёздный"}, ["CLOUDHIS"])
    assert "星光色->Звёздный" in p
    assert "CLOUDHIS" in p
    assert "exactly the same" in p


def test_build_edit_prompt_logos_only():
    p = build_edit_prompt(logos=["CLOUDHIS"])
    assert "CLOUDHIS" in p
    assert "Replace" not in p


def test_build_edit_prompt_translations_only():
    p = build_edit_prompt(translations={"杯": "Чашка"})
    assert "杯->Чашка" in p
    assert "CLOUDHIS" not in p


class FakeStorage:
    def __init__(self):
        self.put_called = False
    def put(self, key, data, mime="image/png"):
        self.put_called = True
        return "https://cdn.example.com/j.png"


class FakeVLM:
    def __init__(self):
        self.called = False
    async def translate(self, url, hint, **kw):
        self.called = True
        return "https://cdn.example.com/vlm.png"


def _adapter(handler, **kw):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = FakeStorage()
    vlm = FakeVLM()
    ad = JimengEditAdapter(http, "sess", "http://x", "jimeng-4.0", storage,
                           fallback_translator=vlm, **kw)
    return ad, storage, vlm


async def test_happy_path():
    def handler(request):
        if request.url.path == "/v1/images/generations":
            body = json.loads(request.content)
            assert body["images"] == ["https://img/a.jpg"]
            assert request.headers["authorization"] == "Bearer sess"
            assert "Replace text with Russian" in body["prompt"]
            return httpx.Response(200, json={"data": [{"url": "https://jimeng/x.png"}]})
        return httpx.Response(200, content=b"img")

    ad, storage, vlm = _adapter(handler)
    out = await ad.translate("https://img/a.jpg", "hint",
                             translations={"杯": "Чашка"}, logos=["CLOUDHIS"])
    assert out == "https://cdn.example.com/j.png"
    assert storage.put_called and not vlm.called


async def test_no_translations_returns_original():
    ad, _, vlm = _adapter(lambda req: httpx.Response(200, content=b"img"))
    out = await ad.translate("https://img/a.jpg", "hint")
    assert out == "https://img/a.jpg"
    assert not vlm.called


async def test_sidecar_error_falls_back():
    def handler(req):
        if req.url.path == "/v1/images/generations":
            return httpx.Response(500, json={"error": "busy"})
        return httpx.Response(200, content=b"img")

    ad, storage, vlm = _adapter(handler)
    out = await ad.translate("https://img/a.jpg", "hint",
                             translations={"a": "b"}, logos=["X"])
    assert out == "https://cdn.example.com/vlm.png"
    assert vlm.called and not storage.put_called
