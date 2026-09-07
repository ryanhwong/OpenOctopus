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


class _DetectClient:
    """返回固定 boxes 的假 VLM，用于 detect_and_translate。"""
    def __init__(self, boxes):
        self._boxes = boxes
    @property
    def chat(self):
        return _Chat(self._boxes)


class _Chat:
    def __init__(self, boxes):
        self.completions = _Completions(boxes)


class _Completions:
    def __init__(self, boxes):
        self._boxes = boxes
    async def create(self, **kw):
        msg = type("M", (), {"content": json.dumps({"boxes": self._boxes})})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


async def test_no_text_in_image_returns_original():
    def handler(req):
        return httpx.Response(200, content=b"imgbytes")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ad = JimengEditAdapter(http, _DetectClient([]), "m", FakeStorage(),
                           fallback_translator=FakeVLM())
    assert await ad.translate("https://img/a.jpg", "hint") == "https://img/a.jpg"


async def test_cli_error_falls_back(monkeypatch):
    import openoctopus.image.jimeng as jimeng_mod

    async def boom(*args, **kwargs):
        raise RuntimeError("cli down")

    monkeypatch.setattr(jimeng_mod, "_run_cli", boom)
    boxes = [{"x": 1, "y": 1, "w": 10, "h": 10, "zh_text": "星光色", "ru_text": "Звёздный"}]
    def handler(req):
        return httpx.Response(200, content=b"imgbytes")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vlm = FakeVLM()
    ad = JimengEditAdapter(http, _DetectClient(boxes), "m", FakeStorage(),
                           fallback_translator=vlm)
    out = await ad.translate("https://img/a.jpg", "hint")
    assert out == "https://cdn.example.com/vlm.png"
    assert vlm.called


async def test_cli_success_uploads(monkeypatch):
    import openoctopus.image.jimeng as jimeng_mod

    async def fake_cli(args, timeout=180):
        assert "image2image" in args
        assert args[args.index("--model_version") + 1] == "4.0"
        assert args[args.index("--generate_num") + 1] == "1"
        prompt = args[args.index("--prompt") + 1]
        assert "星光色->Звёздный" in prompt
        return {"gen_status": "success",
                "result_json": {"images": [{"image_url": "https://jimeng/out.png"}]}}

    monkeypatch.setattr(jimeng_mod, "_run_cli", fake_cli)
    boxes = [{"x": 1, "y": 1, "w": 10, "h": 10, "zh_text": "星光色", "ru_text": "Звёздный"}]
    def handler(req):
        if req.url.path.endswith("/out.png"):
            return httpx.Response(200, content=b"imgbytes")
        return httpx.Response(200, content=b"source")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = FakeStorage()
    ad = JimengEditAdapter(http, _DetectClient(boxes), "m", storage, model="4.0",
                           fallback_translator=FakeVLM())
    out = await ad.translate("https://img/a.jpg", "hint")
    assert out == "https://cdn.example.com/j.png"
    assert storage.put_called


async def test_logo_only_box_no_translate(monkeypatch):
    """只检测到英文 logo（ru_text 空）→ 只抹不翻。"""
    import openoctopus.image.jimeng as jimeng_mod

    async def fake_cli(args, timeout=180):
        prompt = args[args.index("--prompt") + 1]
        assert "CLOUDHIS" in prompt
        assert "Replace text" not in prompt
        return {"gen_status": "success",
                "result_json": {"images": [{"image_url": "https://jimeng/out.png"}]}}

    monkeypatch.setattr(jimeng_mod, "_run_cli", fake_cli)
    boxes = [{"x": 1, "y": 1, "w": 10, "h": 10, "zh_text": "CLOUDHIS", "ru_text": ""}]
    def handler(req):
        if req.url.path.endswith("/out.png"):
            return httpx.Response(200, content=b"imgbytes")
        return httpx.Response(200, content=b"source")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = FakeStorage()
    ad = JimengEditAdapter(http, _DetectClient(boxes), "m", storage, model="4.0",
                           fallback_translator=FakeVLM())
    out = await ad.translate("https://img/a.jpg", "hint")
    assert out == "https://cdn.example.com/j.png"
    assert storage.put_called