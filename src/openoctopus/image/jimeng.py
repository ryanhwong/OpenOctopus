"""即梦图生图适配器：VLM 检测拿译文 -> sidecar 重绘 -> R2 托管。

失败时回落到 VLM 管线，保证单图永不阻塞整单。
"""

import hashlib

import httpx

from openoctopus.image.detect import detect_and_translate
from openoctopus.image.pipeline import downscale_for_vlm


def build_edit_prompt(boxes) -> str:
    repl = [f"{b.zh_text}->{b.ru_text}" for b in boxes if b.ru_text]
    rem = [b.zh_text for b in boxes if not b.ru_text and b.zh_text]
    parts = [("Edit this e-commerce product photo. "
              "Keep the product, hands, background, colors and composition exactly the same.")]
    if repl:
        parts.append("Replace text with Russian: " + "; ".join(repl))
    if rem:
        parts.append("Completely remove these texts and fill with surrounding background: "
                     + "; ".join(rem))
    return " ".join(parts)


class JimengEditAdapter:
    def __init__(self, http: httpx.AsyncClient, session_id: str, base_url: str,
                 model: str, llm_client, llm_model: str, storage,
                 fallback_translator=None):
        self.http = http
        self.session_id = session_id
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.llm_client = llm_client
        self.llm_model = llm_model
        self.storage = storage
        self.fallback_translator = fallback_translator

    async def translate(self, image_url: str, key_hint: str) -> str:
        try:
            return await self._translate(image_url, key_hint)
        except Exception as e:
            if self.fallback_translator is None:
                raise
            print(f"[jimeng] failed ({type(e).__name__}), falling back to VLM pipeline",
                  flush=True)
            return await self.fallback_translator.translate(image_url, key_hint)

    async def _translate(self, image_url: str, key_hint: str) -> str:
        r = await self.http.get(image_url, timeout=60)
        r.raise_for_status()
        small, _ = downscale_for_vlm(r.content)
        boxes = await detect_and_translate(self.llm_client, self.llm_model, small)
        if not boxes:
            return image_url
        out_url = await self._generate(image_url, build_edit_prompt(boxes))
        if self.storage is None:
            return out_url
        img = await self.http.get(out_url, timeout=120)
        img.raise_for_status()
        key = f"{key_hint}-jimeng-{hashlib.sha1(image_url.encode()).hexdigest()[:10]}.png"
        return self.storage.put(key, img.content)

    async def _generate(self, image_url: str, prompt: str) -> str:
        r = await self.http.post(
            self.base_url + "/v1/images/generations",
            json={"model": self.model, "prompt": prompt,
                  "images": [image_url], "response_format": "url"},
            headers={"Authorization": f"Bearer {self.session_id}",
                     "Content-Type": "application/json"},
            timeout=300,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data or "url" not in data[0]:
            raise RuntimeError(f"jimeng returned no image: {str(data)[:120]}")
        return data[0]["url"]
