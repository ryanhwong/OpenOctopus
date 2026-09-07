"""即梦图生图：简单直传 prompt，不依赖 VLM 检测。"""

import hashlib

import httpx


def build_edit_prompt(translations: dict[str, str] | None = None,
                      logos: list[str] | None = None) -> str:
    parts = [("Edit this e-commerce product photo. "
              "Keep the product, hands, background, colors and composition exactly the same.")]
    if translations:
        repl = [f"{zh}->{ru}" for zh, ru in translations.items()]
        parts.append("Replace text with Russian: " + "; ".join(repl))
    if logos:
        parts.append("Completely remove these brand texts and fill with surrounding background: "
                     + "; ".join(logos))
    return " ".join(parts)


class JimengEditAdapter:
    def __init__(self, http: httpx.AsyncClient, session_id: str, base_url: str,
                 model: str, storage, fallback_translator=None):
        self.http = http
        self.session_id = session_id
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.storage = storage
        self.fallback_translator = fallback_translator

    async def translate(self, image_url: str, key_hint: str,
                        translations: dict[str, str] | None = None,
                        logos: list[str] | None = None) -> str:
        try:
            prompt = build_edit_prompt(translations, logos)
            if not prompt or not translations and not logos:
                return image_url
            out_url = await self._generate(image_url, prompt)
            if self.storage is None:
                return out_url
            img = await self.http.get(out_url, timeout=120)
            img.raise_for_status()
            key = f"{key_hint}-jimeng-{hashlib.sha1(image_url.encode()).hexdigest()[:10]}.png"
            return self.storage.put(key, img.content)
        except Exception as e:
            if self.fallback_translator is None:
                raise
            print(f"[jimeng] failed ({type(e).__name__}), falling back to VLM pipeline",
                  flush=True)
            return await self.fallback_translator.translate(image_url, key_hint)

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
