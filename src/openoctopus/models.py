from pydantic import BaseModel


class Sku(BaseModel):
    props: dict[str, str] = {}
    price_cny: float = 0.0
    image_url: str | None = None


class RawProduct(BaseModel):
    source_url: str
    platform: str
    title_zh: str
    bullets_zh: list[str] = []
    description_zh: str = ""
    price_cny: float = 0.0
    skus: list[Sku] = []
    main_images: list[str] = []
    detail_images: list[str] = []


class TextBox(BaseModel):
    x: int
    y: int
    w: int
    h: int
    zh_text: str
    ru_text: str


class TranslatedContent(BaseModel):
    title_ru: str
    bullets_ru: list[str] = []
    description_ru: str = ""
    model: str = ""
