"""主备 LLM 客户端：主 opencode 网关，异常时自动降级到 OpenRouter。

调用方看到的仍是 `client.chat.completions.create(model=..., ...)` 形态；
wrapper 按后端填入各自的模型 slug（主备模型名不同，透传的 model 会被替换）。
"""


class _Completions:
    def __init__(self, primary, primary_model, fallback, fallback_model):
        self._primary = primary
        self._primary_model = primary_model
        self._fallback = fallback
        self._fallback_model = fallback_model

    async def create(self, **kwargs):
        kwargs.pop("model", None)
        try:
            return await self._primary.create(model=self._primary_model, **kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"[llm] primary failed ({type(e).__name__}), falling back")
            return await self._fallback.create(model=self._fallback_model, **kwargs)


class _Chat:
    def __init__(self, primary, primary_model, fallback, fallback_model):
        self.completions = _Completions(primary, primary_model, fallback, fallback_model)


class FallbackChatClient:
    def __init__(self, primary_client, primary_model: str,
                 fallback_client, fallback_model: str):
        self._primary_client = primary_client
        self._fallback_client = fallback_client
        self.chat = _Chat(primary_client.chat.completions, primary_model,
                          fallback_client.chat.completions, fallback_model)

    async def aclose(self):
        for c in (self._primary_client, self._fallback_client):
            try:
                await c.aclose()
            except Exception:  # noqa: BLE001, S110
                pass
