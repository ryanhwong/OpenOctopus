from dataclasses import dataclass, field

import httpx
from openai import AsyncOpenAI

from openoctopus.collector.adapters import A1688PlaywrightAdapter
from openoctopus.config import Settings
from openoctopus.content.translators import LLMContentTranslator
from openoctopus.db import init_db
from openoctopus.image.pipeline import VlmPipelineTranslator
from openoctopus.llm_fallback import FallbackChatClient
from openoctopus.ozon.client import BASE_URL, OzonClient
from openoctopus.storage.r2 import make_r2


@dataclass
class AppContext:
    settings: Settings
    db_path: str
    adapters: list = field(default_factory=list)
    llm_client: object | None = None
    content_translator: object | None = None
    image_translator: object | None = None
    ozon: OzonClient | None = None
    storage: object | None = None


def build_context(settings: Settings) -> AppContext:
    init_db(settings.db_path)
    ctx = AppContext(settings=settings, db_path=settings.db_path,
                     adapters=[A1688PlaywrightAdapter()])
    primary = AsyncOpenAI(base_url=settings.opencode_base_url,
                          api_key=settings.opencode_api_key or "missing",
                          timeout=120.0, max_retries=1)
    fallback = AsyncOpenAI(base_url=settings.openrouter_base_url,
                           api_key=settings.openrouter_api_key or "missing",
                           timeout=120.0, max_retries=1)
    ctx.llm_client = FallbackChatClient(primary, settings.content_model,
                                        fallback, settings.fallback_content_model)
    ctx.content_translator = LLMContentTranslator(ctx.llm_client, settings.content_model)
    ctx.storage = make_r2(settings)
    vlm = VlmPipelineTranslator(
        FallbackChatClient(primary, settings.image_model,
                           fallback, settings.fallback_image_model),
        settings.image_model, ctx.storage, settings.font_path,
        httpx.AsyncClient(timeout=60))
    if (settings.image_backend or "vlm").lower() == "jimeng":
        from openoctopus.image.jimeng import JimengEditAdapter

        ctx.image_translator = JimengEditAdapter(
            http=httpx.AsyncClient(timeout=320),
            session_id=settings.jimeng_session_id,
            base_url=settings.jimeng_base_url,
            model=settings.jimeng_model,
            llm_client=FallbackChatClient(primary, settings.image_model,
                                          fallback, settings.fallback_image_model),
            llm_model=settings.image_model,
            storage=ctx.storage,
            fallback_translator=vlm)
    else:
        ctx.image_translator = vlm
    ctx.ozon = OzonClient(httpx.AsyncClient(base_url=BASE_URL, timeout=60),
                          settings.ozon_client_id, settings.ozon_api_key)
    return ctx
