
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
    ad = JimengEditAdapter(http, FakeStorage(), fallback_translator=FakeVLM())
    assert await ad.translate("https://img/a.jpg", "hint") == "https://img/a.jpg"


async def test_cli_error_falls_back(monkeypatch):
    import openoctopus.image.jimeng as jimeng_mod

    async def boom(*args, **kwargs):
        raise RuntimeError("cli down")

    monkeypatch.setattr(jimeng_mod, "_run_cli", boom)
    def noop(req):
        return httpx.Response(200, content=b"img")
    http = httpx.AsyncClient(transport=httpx.MockTransport(noop))
    vlm = FakeVLM()
    ad = JimengEditAdapter(http, FakeStorage(), fallback_translator=vlm)
    out = await ad.translate("https://img/a.jpg", "hint",
                             translations={"a": "b"}, logos=["X"])
    assert out == "https://cdn.example.com/vlm.png"
    assert vlm.called


async def test_cli_success_uploads(monkeypatch):
    import openoctopus.image.jimeng as jimeng_mod

    async def fake_cli(args, timeout=180):
        assert "image2image" in args
        assert "--model_version" in args
        assert args[args.index("--model_version") + 1] == "4.0"
        assert "--generate_num" in args
        assert args[args.index("--generate_num") + 1] == "1"
        return {"gen_status": "success",
                "result_json": {"images": [{"image_url": "https://jimeng/out.png"}]}}

    monkeypatch.setattr(jimeng_mod, "_run_cli", fake_cli)
    def handler(req):
        if req.url.path.endswith("/out.png"):
            return httpx.Response(200, content=b"imgbytes")
        return httpx.Response(200, content=b"source")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = FakeStorage()
    ad = JimengEditAdapter(http, storage, model="4.0", fallback_translator=FakeVLM())
    out = await ad.translate("https://img/a.jpg", "hint",
                             translations={"杯": "Чашка"})
    assert out == "https://cdn.example.com/j.png"
    assert storage.put_called
