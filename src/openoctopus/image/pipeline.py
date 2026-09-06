import hashlib
from io import BytesIO

import httpx
from PIL import Image

from openoctopus.image.detect import detect_and_translate
from openoctopus.image.render import translate_image_bytes
from openoctopus.models import TextBox

MAX_VLM_SIDE = 1024


def downscale_for_vlm(data: bytes, max_side: int = MAX_VLM_SIDE) -> tuple[bytes, float]:
    """VLM 识别用小图（省 token 提速）；返回 (小图字节, 缩放比)，原图坐标 = 小图坐标 / 缩放比。"""
    try:
        img = Image.open(BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001
        return data, 1.0
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale >= 1.0:
        return data, 1.0
    small = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    buf = BytesIO()
    small.save(buf, "PNG")
    return buf.getvalue(), scale


def _rescale_boxes(boxes: list[TextBox], scale: float) -> list[TextBox]:
    if scale >= 1.0:
        return boxes
    return [TextBox(x=int(b.x / scale), y=int(b.y / scale),
                    w=int(b.w / scale), h=int(b.h / scale),
                    zh_text=b.zh_text, ru_text=b.ru_text) for b in boxes]


class VlmPipelineTranslator:
    def __init__(self, client, model: str, storage, font_path: str,
                 http: httpx.AsyncClient | None = None,
                 render=None):
        self.client = client
        self.model = model
        self.storage = storage
        self.font_path = font_path
        self.http = http or httpx.AsyncClient(timeout=60)
        self.render = render or translate_image_bytes

    async def translate(self, image_url: str, key_hint: str) -> str:
        r = await self.http.get(image_url)
        r.raise_for_status()
        data = r.content
        small, scale = downscale_for_vlm(data)
        boxes = await detect_and_translate(self.client, self.model, small)
        if not boxes or self.storage is None:
            return image_url
        # 重绘用原图全分辨率，坐标按比例放大回去
        out = self.render(data, _rescale_boxes(boxes, scale), self.font_path)
        key = f"{key_hint}-{hashlib.sha1(image_url.encode()).hexdigest()[:10]}.png"
        return self.storage.put(key, out)
