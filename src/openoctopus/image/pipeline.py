import hashlib

import httpx

from openoctopus.image.detect import detect_and_translate
from openoctopus.image.render import translate_image_bytes


class VlmPipelineTranslator:
    def __init__(self, client, model: str, storage, font_path: str,
                 http: httpx.AsyncClient | None = None):
        self.client = client
        self.model = model
        self.storage = storage
        self.font_path = font_path
        self.http = http or httpx.AsyncClient(timeout=60)

    async def translate(self, image_url: str, key_hint: str) -> str:
        r = await self.http.get(image_url)
        r.raise_for_status()
        data = r.content
        boxes = await detect_and_translate(self.client, self.model, data)
        if not boxes or self.storage is None:
            return image_url
        out = translate_image_bytes(data, boxes, self.font_path)
        key = f"{key_hint}-{hashlib.sha1(image_url.encode()).hexdigest()[:10]}.png"
        return self.storage.put(key, out)
