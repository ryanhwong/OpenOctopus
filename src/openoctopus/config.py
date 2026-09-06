from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_path: str = "data/openoctopus.db"
    live_mode: bool = False
    price_cny_to_rub: float = 12.0

    ozon_client_id: str = ""
    ozon_api_key: str = ""

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    content_model: str = "deepseek-v4-flash"
    image_model: str = "deepseek-v4-flash-vision-exp"
    fallback_content_model: str = "minimax/minimax-m2.7:free"
    fallback_image_model: str = "minimax/minimax-m3:free"

    opencode_api_key: str = ""
    opencode_base_url: str = "https://opencode.ai/zen/v1"

    r2_endpoint: str = ""
    r2_bucket: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_public_base_url: str = ""

    font_path: str = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
    playwright_storage_state: str = "data/playwright_state.json"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
