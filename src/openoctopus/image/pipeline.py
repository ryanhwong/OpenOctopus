import hashlib
from io import BytesIO

import httpx
from PIL import Image

from openoctopus.image.detect import LEFTOVER_PROMPT, detect_and_translate
from openoctopus.image.render import erase_boxes, translate_image_bytes
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


def _iou(a: TextBox, b: TextBox) -> float:
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


def _leftover_boxes(first: list[TextBox], second: list[TextBox]) -> list[TextBox]:
    """第二遍只处理与第一遍面板区基本不重叠的残留，不动俄文译文。"""
    return [b for b in second
            if all(_iou(b, f) < 0.1 for f in first)]


def _fit_boxes_to_image(boxes: list[TextBox], width: int, height: int) -> list[TextBox]:
    """把框钳制到图片范围内；疑似 0-1000 归一化坐标则换算；废框丢弃。"""
    out: list[TextBox] = []
    for b in boxes:
        x0, y0, x1, y1 = b.x, b.y, b.x + b.w, b.y + b.h
        if (max(x0, x1) > width or max(y0, y1) > height) and max(x0, y0, x1, y1) <= 1000:
            fx, fy = width / 1000.0, height / 1000.0
            x0, y0, x1, y1 = x0 * fx, y0 * fy, x1 * fx, y1 * fy
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(width, int(x1)), min(height, int(y1))
        if x1 > x0 and y1 > y0:
            out.append(TextBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0,
                               zh_text=b.zh_text, ru_text=b.ru_text))
    return out


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
        # 重绘用原图全分辨率，坐标按比例放大回去，再钳制到图片范围
        try:
            img_w, img_h = Image.open(BytesIO(data)).size
        except Exception:  # noqa: BLE001
            img_w, img_h = 0, 0
        if img_w and img_h:
            boxes = _fit_boxes_to_image(_rescale_boxes(boxes, scale), img_w, img_h)
        else:
            boxes = _rescale_boxes(boxes, scale)
        if not boxes:
            return image_url
        out = self.render(data, boxes, self.font_path)
        out = await self._cleanup_leftovers(out, boxes)
        key = f"{key_hint}-{hashlib.sha1(image_url.encode()).hexdigest()[:10]}.png"
        return self.storage.put(key, out)

    async def _cleanup_leftovers(self, rendered: bytes,
                                 first_boxes: list[TextBox]) -> bytes:
        """渲染完再扫一遍残留中文/英文 logo，只抹面板区之外的，俄文不动。失败则原样返回。"""
        try:
            small, scale = downscale_for_vlm(rendered)
            second = await detect_and_translate(self.client, self.model, small,
                                                LEFTOVER_PROMPT)
            img = Image.open(BytesIO(rendered)).convert("RGB")
            cands = _fit_boxes_to_image(_rescale_boxes(second, scale), *img.size)
            leftovers = _leftover_boxes(first_boxes, cands)
            if not leftovers:
                return rendered
            out = erase_boxes(img, leftovers)
            buf = BytesIO()
            out.save(buf, "PNG")
            return buf.getvalue()
        except Exception:  # noqa: BLE001
            return rendered
