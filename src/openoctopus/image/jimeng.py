"""即梦官方 CLI 图生图 adapter。

每张图独立处理：
1. VLM 读取图里实际有哪些中文/品牌文字（detect_and_translate）
2. 只把「图里真有的中文 -> 对应俄语」写进 prompt 让即梦重绘
3. 图里没有文字/logo -> 原样返回，不调即梦（不硬搬标题翻译）
"""

import asyncio
import hashlib
import os
import tempfile

import httpx

from openoctopus.image.detect import detect_and_translate
from openoctopus.image.pipeline import downscale_for_vlm

CLI_PATH = os.path.expanduser("~/.dreamina_cli/dreamina")


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


async def _run_cli(args: list[str], timeout: int = 180) -> dict:
    """运行 dreamina CLI，返回解析后的 JSON。"""
    import json

    env = {k: v for k, v in os.environ.items()
           if not k.upper().endswith("_PROXY") and k.lower() != "all_proxy"}
    proc = await asyncio.create_subprocess_exec(
        CLI_PATH, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("dreamina CLI timed out")
    if proc.returncode != 0:
        raise RuntimeError(f"dreamina CLI failed ({proc.returncode}): "
                           f"{stderr.decode()[:300]} {stdout.decode()[:300]}")
    return json.loads(stdout.decode())


class JimengEditAdapter:
    def __init__(self, http: httpx.AsyncClient, llm_client, llm_model: str,
                 storage, model: str = "4.0", fallback_translator=None,
                 ratio: str = "1:1"):
        self.http = http
        self.llm_client = llm_client
        self.llm_model = llm_model
        self.storage = storage
        self.model = model
        self.fallback_translator = fallback_translator
        self.ratio = ratio

    async def translate(self, image_url: str, key_hint: str, prompt_override: str | None = None,
                        **kwargs) -> str:
        try:
            # download source
            r = await self.http.get(image_url, timeout=60)
            r.raise_for_status()
            data = r.content

            if prompt_override:
                prompt = prompt_override
            else:
                # VLM 读图：图里实际有哪些中文/品牌文字（含翻译）
                small, _ = downscale_for_vlm(data)
                boxes = await detect_and_translate(self.llm_client, self.llm_model, small)
                if not boxes:
                    return image_url  # 图里没有文字，原样返回

                # 只处理图里真有的文字
                translations = {b.zh_text: b.ru_text for b in boxes if b.ru_text and b.zh_text}
                logos = [b.zh_text for b in boxes if not b.ru_text and b.zh_text]
                if not translations and not logos:
                    return image_url  # 全是空文本，不处理

                prompt = build_edit_prompt(translations or None, logos or None)

            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                f.write(data)
                local_path = f.name
            try:
                out_url = await self._generate(local_path, prompt)
            finally:
                os.unlink(local_path)

            if self.storage is None:
                return out_url
            img = await self.http.get(out_url, timeout=120)
            img.raise_for_status()
            key = f"{key_hint}-jimeng-{hashlib.sha1(image_url.encode()).hexdigest()[:10]}.png"
            return self.storage.put(key, img.content)
        except Exception as e:
            if self.fallback_translator is None:
                raise
            print(f"[jimeng-cli] failed ({type(e).__name__}): {e}", flush=True)
            return await self.fallback_translator.translate(image_url, key_hint)

    async def _generate(self, local_path: str, prompt: str) -> str:
        data = await _run_cli([
            "image2image",
            "--images", local_path,
            "--prompt", prompt,
            "--model_version", self.model,
            "--ratio", self.ratio,
            "--resolution_type", "2k",
            "--generate_num", "1",
            "--poll", "120",
        ])
        if data.get("gen_status") != "success":
            raise RuntimeError(f"dreamina not success: {data.get('gen_status')} "
                               f"{data.get('fail_reason', '')}")
        images = (data.get("result_json") or {}).get("images", [])
        if not images or "image_url" not in images[0]:
            raise RuntimeError(f"dreamina no image: {str(data)[:200]}")
        return images[0]["image_url"]
