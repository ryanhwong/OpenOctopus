"""即梦 4.0 图生图 adapter：绕过 sidecar broken img2img，直连内部 API。

sidecar 的 img2img 路径没有正确把 uploadedImageIds 绑到 blend 能力列表
（abilityList 为空），导致即梦把我们的参考图当文字生图处理。
本模块直接组装正确的 blend 能力 + prompt placeholder，确保即梦基于原图编辑。
"""

import asyncio
import hashlib
import json
import uuid

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
        self._draft_id = str(uuid.uuid4())
        self._component_id = str(uuid.uuid4())
        self._submit_id = str(uuid.uuid4())

    async def translate(self, image_url: str, key_hint: str,
                        translations: dict[str, str] | None = None,
                        logos: list[str] | None = None) -> str:
        try:
            prompt = build_edit_prompt(translations, logos)
            if not prompt or (not translations and not logos):
                return image_url
            # step 1: upload reference image to jimeng blob store
            image_id = await self._upload_image(image_url)
            # step 2: build correct blend payload (sidecar 的 blend 是空的，这里是修复)
            out_url = await self._generate(prompt, image_id)
            # step 3: download result to R2
            if self.storage is None:
                return out_url
            img = await self.http.get(out_url, timeout=120)
            img.raise_for_status()
            key = f"{key_hint}-jimeng-{hashlib.sha1(image_url.encode()).hexdigest()[:10]}.png"
            return self.storage.put(key, img.content)
        except Exception as e:
            if self.fallback_translator is None:
                raise
            print(f"[jimeng] failed ({type(e).__name__}): {e}", flush=True)
            return await self.fallback_translator.translate(image_url, key_hint)

    async def _upload_image(self, url: str) -> str:
        """上传图片到 jimeng blob store，返回 imageId。"""
        # download from source
        r = await self.http.get(url, timeout=60)
        r.raise_for_status()
        # upload via sidecar's upload endpoint (reuses auth/region logic)
        upload_resp = await self.http.post(
            self.base_url + "/v1/upload/image",
            headers={"Authorization": f"Bearer {self.session_id}"},
            json={"url": url},
            timeout=60,
        )
        if upload_resp.status_code == 200:
            return upload_resp.json().get("image_id", upload_resp.json().get("id", ""))
        # fallback: upload raw bytes via imagex API (same as sidecar)
        return await self._upload_to_imagex(url)

    async def _upload_to_imagex(self, url: str) -> str:
        """通过即梦内部 imagex 上传图片。"""
        img_bytes = (await self.http.get(url, timeout=60)).content
        resp = await self.http.post(
            self.base_url + "/mweb/v1/get_upload_token",
            headers={"Authorization": f"Bearer {self.session_id}"},
            json={},
            timeout=30,
        )
        resp.raise_for_status()
        token_data = resp.json().get("data", {})
        service_id = token_data.get("service_id", "")
        _ = service_id
        token = token_data.get("token", "")
        upload_url = token_data.get("upload_url", "")

        if not upload_url:
            raise RuntimeError("no upload_url from jimeng")

        # upload via imagex
        img_resp = await self.http.post(
            upload_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"},
            content=img_bytes,
            timeout=30,
        )
        img_resp.raise_for_status()
        uri = img_resp.json().get("result", {}).get("uri", "")
        if not uri:
            raise RuntimeError(f"no uri from imagex: {img_resp.text[:200]}")
        return uri

    async def _generate(self, prompt: str, image_id: str) -> str:
        """构建正确的 blend payload 并提交生成任务。"""
        session_id = self.session_id
        region_info = _parse_region(session_id)

        # step A: build blend ability list (sidecar 这步是空的，这里正确组装)
        ability_id = str(uuid.uuid4())
        ability_list = [{
            "abilityName": "byte_edit",
            "strength": 0.5,
            "id": ability_id,
            "upload_image_ids": [{"id": image_id}],
            "source": {"imageUrl": f"blob:https://jimeng.jianying.com/{uuid.uuid4()}"},
        }]

        # step B: build prompt placeholder list (1张图 → 1个 placeholder)
        prompt_placeholder = [{
            "type": "image",
            "index": 0,
            "id": str(uuid.uuid4()),
            "title": "",
            "image_id": image_id,
        }]

        # step C: core params
        core_param = {
            "type": "", "id": str(uuid.uuid4()),
            "model": "high_aes_general_v40",
            "prompt": "##" + prompt,
            "sample_strength": 0.5,
            "large_image_info": {
                "type": "", "id": str(uuid.uuid4()),
                "min_version": "3.0.2", "width": 2048, "height": 2048,
                "resolution_type": "2k",
            },
            "intelligent_ratio": False,
            "image_ratio": 1,
            "negative_prompt": "",
            "seed": _random_seed(),
        }

        # step D: blend ability list (sidecar 的 buildBlendAbilityList 是空的——这是 bug 的根源，ability_list 在 step A 已正确组装)

        # step E: draft content
        component_id = str(uuid.uuid4())
        generate_id2 = str(uuid.uuid4())
        draft_content = {
            "type": "draft", "id": self._draft_id,
            "min_version": "3.0.2", "min_features": [], "is_from_tsn": True,
            "version": "3.3.9",
            "main_component_id": component_id,
            "component_list": [{
                "type": "image_base_component", "id": component_id,
                "min_version": "3.0.2", "aigc_mode": "workbench",
                "metadata": {"type": "", "id": str(uuid.uuid4()),
                             "created_platform": 3, "created_platform_version": "",
                             "created_time_in_ms": str(int(asyncio.get_event_loop().time() * 1000)),
                             "created_did": ""},
                "generate_type": "generate",
                "abilities": {
                    "type": "", "id": str(uuid.uuid4()),
                    "generate": {
                        "type": "", "id": generate_id2,
                        "core_param": core_param,
                        "gen_option": {"type": "", "id": str(uuid.uuid4()), "generate_all": False},
                    },
                },
            }],
            "draft_components": [{
                "type": "generate",
                "id": generate_id2,
                "ability_list": ability_list,
                "prompt_placeholder_info_list": prompt_placeholder,
                "postedit_param": {"type": "", "id": str(uuid.uuid4()), "generate_type": 0},
            }],
            "postedit_param": {"type": "", "id": str(uuid.uuid4()), "generate_type": 0},
        }

        # step F: request payload
        request_data = {
            "extend": {"root_model": "high_aes_general_v40"},
            "submit_id": self._submit_id,
            "draft_content": json.dumps(draft_content, ensure_ascii=False),
        }

        image_referer = region_info["image_referer"]
        gen_resp = await self.http.post(
            self.base_url + "/mweb/v1/aigc_draft/generate",
            headers={"Authorization": f"Bearer {self.session_id}",
                     "Referer": image_referer,
                     "Content-Type": "application/json"},
            json=request_data,
            timeout=30,
        )
        gen_resp.raise_for_status()
        gen_data = gen_resp.json().get("data", {})
        history_id = gen_data.get("aigc_data", {}).get("history_record_id")
        if not history_id:
            raise RuntimeError(f"no history_record_id: {gen_resp.text[:200]}")

        # step G: poll result
        return await self._poll_result(history_id)

    async def _poll_result(self, history_id: str) -> str:
        poll_url = self.base_url + "/mweb/v1/get_history_by_ids"
        for _ in range(180):
            await asyncio.sleep(20)
            resp = await self.http.post(poll_url, headers={
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"},
                json={"history_ids": [history_id],
                       "image_info": {"width": 2048, "height": 2048, "format": "webp",
                                       "image_scene_list": [{"scene": "normal", "width": 720,
                                                              "height": 720, "uniq_key": "720",
                                                              "format": "webp"}]}},
                timeout=30)
            resp.raise_for_status()
            task = resp.json().get(history_id, {})
            items = task.get("item_list", [])
            urls = [item.get("origin_url") or item.get("url") or "" for item in items]
            urls = [u for u in urls if u]
            if urls:
                return urls[0]
            status = task.get("status", 0)
            if status in (50, 100):
                await asyncio.sleep(10)
        raise RuntimeError("jimeng poll timeout (30min)")


def _parse_region(session_id: str) -> dict:
    if session_id.startswith("us-"):
        return {"isCN": False, "image_referer": "https://dreamina.capcut.com/ai-tool/generate?type=image"}
    return {"isCN": True, "image_referer": "https://jimeng.jianying.com/ai-tool/generate?type=image"}


def _random_seed() -> int:
    import random
    return random.randint(10000000, 99999999)
