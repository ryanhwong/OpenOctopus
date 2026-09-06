import json

from openoctopus.image.pipeline import VlmPipelineTranslator, downscale_for_vlm


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


def test_downscale_large_image():
    import io

    from PIL import Image

    img = Image.new("RGB", (2000, 1000), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    small, scale = downscale_for_vlm(buf.getvalue())
    assert scale == 1024 / 2000
    assert max(Image.open(io.BytesIO(small)).size) == 1024


def test_downscale_invalid_bytes_passthrough():
    assert downscale_for_vlm(b"img") == (b"img", 1.0)


def test_fit_boxes_normalized_rescaled():
    from openoctopus.image.pipeline import _fit_boxes_to_image
    from openoctopus.models import TextBox

    boxes = [TextBox(x=900, y=100, w=50, h=50, zh_text="", ru_text="")]
    out = _fit_boxes_to_image(boxes, 800, 800)
    assert [(b.x, b.y, b.w, b.h) for b in out] == [(720, 80, 40, 40)]


def test_fit_boxes_garbage_dropped():
    from openoctopus.image.pipeline import _fit_boxes_to_image
    from openoctopus.models import TextBox

    boxes = [TextBox(x=5000, y=5000, w=10, h=10, zh_text="", ru_text=""),
             TextBox(x=100, y=100, w=50, h=50, zh_text="", ru_text="")]
    out = _fit_boxes_to_image(boxes, 800, 800)
    assert [(b.x, b.y, b.w, b.h) for b in out] == [(100, 100, 50, 50)]


def test_leftover_filter_keeps_non_overlapping():
    from openoctopus.image.pipeline import _leftover_boxes
    from openoctopus.models import TextBox

    first = [TextBox(x=10, y=10, w=50, h=50, zh_text="", ru_text="")]
    second = [TextBox(x=12, y=12, w=40, h=40, zh_text="", ru_text=""),
              TextBox(x=500, y=500, w=40, h=40, zh_text="", ru_text="")]
    out = _leftover_boxes(first, second)
    assert [(b.x, b.y) for b in out] == [(500, 500)]


class SeqVisionCompletions:
    def __init__(self, replies):
        self.replies = replies
        self.calls = 0

    async def create(self, **kw):
        import json as _json

        self.calls += 1
        payload = {"boxes": self.replies[min(self.calls - 1, len(self.replies) - 1)]}
        msg = type("M", (), {"content": _json.dumps(payload)})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


async def test_second_pass_runs_and_filters():
    from openoctopus.image.pipeline import VlmPipelineTranslator

    comp = SeqVisionCompletions([
        [{"x": 10, "y": 10, "w": 20, "h": 20, "zh_text": "杯", "ru_text": "Чашка"}],
        [{"x": 12, "y": 12, "w": 18, "h": 18, "zh_text": "", "ru_text": ""}],
    ])
    chat = type("Chat", (), {"completions": comp})()
    client = type("Client", (), {"chat": chat})()
    storage = FakeStorage()
    tr = VlmPipelineTranslator(client, "m", storage, "/fonts/x.ttf",
                               http=FakeHttp(b"img"), render=fake_render)
    # b"img" 非法图片 -> downscale 透传；render 固定字节；第二遍 Image.open 失败 -> 原样返回
    result = await tr.translate("https://example.com/a.png", "hint")
    assert result == "https://cdn.example.com/out.png"
    assert comp.calls == 2
    assert storage.put_called is True
