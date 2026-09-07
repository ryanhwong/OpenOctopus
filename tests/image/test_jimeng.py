
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


async def test_no_translations_returns_original():
    def noop(req):
        return httpx.Response(200, content=b"img")
    http = httpx.AsyncClient(transport=httpx.MockTransport(noop))
    storage = FakeStorage()
    vlm = FakeVLM()
    ad = JimengEditAdapter(http, "sess", "http://x",
                           "jimeng-4.0", storage, fallback_translator=vlm)
    out = await ad.translate("https://img/a.jpg", "hint")
    assert out == "https://img/a.jpg"
    assert not vlm.called


async def test_sidecar_error_falls_back():
    def handler(req):
        if "generations" in str(req.url.path):
            return httpx.Response(500, json={"error": "busy"})
        return httpx.Response(200, content=b"img")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = FakeStorage()
    vlm = FakeVLM()
    ad = JimengEditAdapter(http, "sess", "http://x",
                           "jimeng-4.0", storage, fallback_translator=vlm)
    out = await ad.translate("https://img/a.jpg", "hint",
                             translations={"a": "b"}, logos=["X"])
    assert out == "https://cdn.example.com/vlm.png"
    assert vlm.called and not storage.put_called
