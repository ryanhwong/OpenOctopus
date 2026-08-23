# OpenOctopus MVP 实施计划（1688 → Ozon 搬运流水线）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 粘贴 1688 链接（或上传商品页 HTML）→ 自动采集、俄语翻译（文案+图片）、类目映射 → 人审工作台确认 → 经 Ozon Seller API 上架并跟踪结果。

**Architecture:** 本机单体 FastAPI + SQLite（兼任务队列）+ 单 worker 进程；模块 collector/content/image/category/listing/web 经 Protocol 接口解耦；翻译后图片传 Cloudflare R2 取公网 URL。

**Tech Stack:** Python ≥3.11, uv, FastAPI, Jinja2, sqlite3(stdlib), httpx, openai SDK(OpenRouter 兼容), opencv-python-headless, Pillow, boto3(R2 S3 API), Playwright(采集), BeautifulSoup4, pytest + pytest-asyncio。

**Spec:** `docs/superpowers/specs/2026-08-23-ozon-listing-pipeline-design.md`

## Global Constraints

- 包管理用 uv，src 布局，包名 `openoctopus`
- 所有外部 IO 在单测中必须 mock；真实调用由 `LIVE_MODE=1` 门控
- 密钥只放 `.env`（已 gitignore），任何提交文件不得含密钥
- env 变量与 spec §10 一致：`OZON_CLIENT_ID`、`OZON_API_KEY`、`OPENROUTER_API_KEY`、`R2_ENDPOINT`、`R2_BUCKET`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_PUBLIC_BASE_URL`、`CONTENT_MODEL`、`IMAGE_MODEL`、`PRICE_CNY_TO_RUB`、`FONT_PATH`、`DB_PATH`、`LIVE_MODE`、`PLAYWRIGHT_STORAGE_STATE`
- Ozon API 路径集中在 `src/openoctopus/ozon/paths.py`；实现时对照 https://docs.ozon.ru/api/seller 核对版本，版本变化只改该文件
- 图片编辑只在文字 bbox 内进行，框外像素零改动
- 每个 Task 以 commit 结束（conventional commits），测试全绿才 commit
- `uv run ruff check .` 必须通过

---

### Task 1: 项目脚手架 + 配置模块

**Files:**
- Create: `pyproject.toml`(uv init), `src/openoctopus/__init__.py`, `src/openoctopus/config.py`, `.env.example`, `tests/test_config.py`

**Interfaces:**
- Produces: `Settings`（字段见 Global Constraints env 列表）、`get_settings() -> Settings`

- [ ] **Step 1: 初始化**

```bash
uv init --package --name openoctopus . && mkdir -p tests
uv add fastapi "uvicorn[standard]" jinja2 httpx openai opencv-python-headless pillow boto3 pydantic-settings beautifulsoup4 playwright python-multipart
uv add --dev pytest pytest-asyncio ruff
```

在 `pyproject.toml` 追加：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

确认 build backend 指向 `src/openoctopus`（uv init --package 默认 hatchling src 布局即可）。

- [ ] **Step 2: 写失败测试** `tests/test_config.py`

```python
from openoctopus.config import Settings


def test_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("PRICE_CNY_TO_RUB", "13.5")
    monkeypatch.setenv("LIVE_MODE", "1")
    s = Settings()
    assert s.db_path == str(tmp_path / "t.db")
    assert s.price_cny_to_rub == 13.5
    assert s.live_mode is True


def test_defaults():
    s = Settings(_env_file=None)
    assert s.price_cny_to_rub == 12.0
    assert s.live_mode is False
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
```

- [ ] **Step 3: 运行确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: ... config`)

- [ ] **Step 4: 实现** `src/openoctopus/config.py`

```python
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
    content_model: str = "qwen/qwen3-30b-a3b:free"
    image_model: str = "qwen/qwen2.5-vl-72b-instruct:free"

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
```

创建 `.env.example`：列出上述全部变量名，值留空（除 `PRICE_CNY_TO_RUB=12`、默认模型名外），注释说明用途。**不得包含真实密钥。**

- [ ] **Step 5: 通过 + lint**

Run: `uv run pytest tests/test_config.py -v && uv run ruff check .`
Expected: PASS / no errors

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: scaffold project with settings module"
```

---

### Task 2: 数据模型 + SQLite schema

**Files:**
- Create: `src/openoctopus/models.py`, `src/openoctopus/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `Sku(props: dict[str,str], price_cny: float = 0.0, image_url: str | None = None)`
  - `RawProduct(source_url: str, platform: str, title_zh: str, bullets_zh: list[str] = [], description_zh: str = "", price_cny: float = 0.0, skus: list[Sku] = [], main_images: list[str] = [], detail_images: list[str] = [])`
  - `TextBox(x: int, y: int, w: int, h: int, zh_text: str, ru_text: str)`
  - `TranslatedContent(title_ru: str, bullets_ru: list[str] = [], description_ru: str = "", model: str = "")`
  - `init_db(path: str) -> None`; `get_conn(path: str) -> sqlite3.Connection`
  - 表：products, source_snapshots, translations, images, category_mappings, jobs, listings, ozon_categories

- [ ] **Step 1: 写失败测试** `tests/test_db.py`

```python
from openoctopus.db import get_conn, init_db
from openoctopus.models import RawProduct


TABLES = {"products", "source_snapshots", "translations", "images",
          "category_mappings", "jobs", "listings", "ozon_categories"}


def test_init_db_creates_tables(tmp_path):
    p = tmp_path / "t.db"
    init_db(str(p))
    conn = get_conn(str(p))
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_product_insert_and_status(tmp_path):
    p = tmp_path / "t.db"
    init_db(str(p))
    conn = get_conn(str(p))
    conn.execute("INSERT INTO products(source_url, platform, status) VALUES('https://detail.1688.com/offer/123.html','1688','new')")
    row = dict(conn.execute("SELECT * FROM products").fetchone())
    assert row["status"] == "new"


def test_models_defaults():
    rp = RawProduct(source_url="u", platform="1688", title_zh="T")
    assert rp.main_images == [] and rp.skus == []
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL (no module `openoctopus.db`)

- [ ] **Step 3: 实现** `src/openoctopus/models.py`

```python
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
```

- [ ] **Step 4: 实现** `src/openoctopus/db.py`

```python
import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY,
  source_url TEXT UNIQUE,
  platform TEXT NOT NULL DEFAULT '1688',
  status TEXT NOT NULL DEFAULT 'new',
  price_rub REAL,
  ozon_product_id TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS source_snapshots(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  raw_json TEXT NOT NULL,
  fetched_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS translations(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  field TEXT NOT NULL,
  zh TEXT DEFAULT '',
  ru TEXT DEFAULT '',
  model TEXT DEFAULT '',
  edited_by_human INTEGER DEFAULT 0,
  UNIQUE(product_id, field));

CREATE TABLE IF NOT EXISTS images(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  kind TEXT NOT NULL DEFAULT 'main',
  source_url TEXT NOT NULL,
  translated_url TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  meta_json TEXT DEFAULT '{}');

CREATE TABLE IF NOT EXISTS category_mappings(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  ozon_category_id TEXT,
  attributes_json TEXT DEFAULT '{}',
  human_confirmed INTEGER DEFAULT 0,
  UNIQUE(product_id));

CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',
  retries INTEGER DEFAULT 0,
  error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS listings(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  import_task_id TEXT,
  result_json TEXT,
  submitted_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS ozon_categories(
  id TEXT PRIMARY KEY,
  parent_id TEXT,
  title TEXT,
  schema_json TEXT DEFAULT '{}',
  synced_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def get_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(path: str) -> None:
    conn = get_conn(path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
```

- [ ] **Step 5: 通过 + lint + Commit**

Run: `uv run pytest tests/test_db.py -v && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: domain models and sqlite schema"
```

### Task 3: 采集模块（Playwright 主路径 + HTML 文件兜底）

**Files:**
- Create: `src/openoctopus/collector/__init__.py`, `src/openoctopus/collector/base.py`, `src/openoctopus/collector/html_parse.py`, `src/openoctopus/collector/adapters.py`, `src/openoctopus/login.py`
- Test: `tests/collector/test_parse.py`, fixture: `tests/fixtures/1688_page.html`
- Create: `tests/fixtures/1688_page.html`

**Interfaces:**
- Consumes: `RawProduct`、`Settings.playwright_storage_state`
- Produces:
  - `SourceAdapter` Protocol：`platform: ClassVar[str]`；`async fetch(url: str) -> RawProduct`
  - `get_adapter(url: str) -> SourceAdapter`（无匹配抛 `ValueError`）
  - `parse_product_html(html: str, source_url: str) -> RawProduct`（纯函数，Playwright 与 HTML 上传共用）
  - `A1688PlaywrightAdapter.matches(url) -> bool`：host 以 `1688.com` 结尾
  - `python -m openoctopus login`：打开有头浏览器人工扫码，登录后保存 storage_state JSON

**选择器约定（唯一需要随真实页面维护的点）：** 标题=`meta[property="og:title"]`；价格=首个 `.price` 元素文本中的数字；主图=`div.detail-gallery img[src]` 去重；详情图=容器 `.content-detail img[data-src|src]`。实现时用一张真实保存的页面校准一次，之后只改 `html_parse.py`。

- [ ] **Step 1: 写失败测试** `tests/collector/test_parse.py`

```python
from pathlib import Path

from openoctopus.collector.html_parse import parse_product_html

FIXTURE = Path(__file__).parent.parent / "fixtures" / "1688_page.html"


def test_parse_fixture():
    rp = parse_product_html(FIXTURE.read_text(encoding="utf-8"),
                            "https://detail.1688.com/offer/123.html")
    assert rp.platform == "1688"
    assert "保温杯" in rp.title_zh
    assert rp.price_cny == 12.5
    assert len(rp.main_images) == 2
    assert "https://cbu01.alicdn.com/img/detail1.jpg" in rp.detail_images


def test_adapter_matching():
    from openoctopus.collector.adapters import A1688PlaywrightAdapter
    from openoctopus.collector.base import get_adapter
    assert A1688PlaywrightAdapter.matches("https://detail.1688.com/offer/9.html")
    assert not A1688PlaywrightAdapter.matches("https://item.taobao.com/x.htm")
    assert isinstance(get_adapter("https://detail.1688.com/offer/9.html"), A1688PlaywrightAdapter)
```

fixture `tests/fixtures/1688_page.html`（最小化但覆盖全部选择器）：

```html
<!doctype html><html><head>
<meta property="og:title" content="304不锈钢保温杯 大容量便携水杯">
</head><body>
<div class="price"><span>¥</span>12.50</div>
<div class="detail-gallery">
  <img src="https://cbu01.alicdn.com/img/main1.jpg">
  <img src="https://cbu01.alicdn.com/img/main2.jpg">
</div>
<div class="content-detail">
  <p>介绍<img data-src="https://cbu01.alicdn.com/img/detail1.jpg"></p>
</div>
</body></html>
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/collector/test_parse.py -v`
Expected: FAIL (no module)

- [ ] **Step 3: 实现** `src/openoctopus/collector/html_parse.py`

```python
import re

from bs4 import BeautifulSoup

from openoctopus.models import RawProduct


def _first_number(text: str) -> float:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else 0.0


def parse_product_html(html: str, source_url: str) -> RawProduct:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if tag := soup.select_one('meta[property="og:title"]'):
        title = tag.get("content", "").strip()
    price = _first_number(soup.select_one(".price").get_text() if soup.select_one(".price") else "")

    main = []
    for img in soup.select("div.detail-gallery img[src]"):
        if img["src"] not in main:
            main.append(img["src"])

    detail = []
    for img in soup.select(".content-detail img"):
        u = img.get("data-src") or img.get("src") or ""
        if u.startswith("//"):
            u = "https:" + u
        if u and u not in detail:
            detail.append(u)

    return RawProduct(source_url=source_url, platform="1688", title_zh=title,
                      price_cny=price, main_images=main, detail_images=detail)
```

- [ ] **Step 4: 实现** `src/openoctopus/collector/base.py`

```python
from typing import ClassVar, Protocol

from openoctopus.models import RawProduct


class SourceAdapter(Protocol):
    platform: ClassVar[str]
    async def fetch(self, url: str) -> RawProduct: ...


_REGISTRY: list[type] = []


def register(cls: type) -> type:
    _REGISTRY.append(cls)
    return cls


def get_adapter(url: str):
    for cls in _REGISTRY:
        if cls.matches(url):
            return cls()
    raise ValueError(f"no adapter matches {url}")
```

- [ ] **Step 5: 实现** `src/openoctopus/collector/adapters.py`

```python
import asyncio
from pathlib import Path

from httpx import AsyncClient

from openoctopus.collector.base import register
from openoctopus.collector.html_parse import parse_product_html
from openoctopus.config import get_settings


@register
class A1688PlaywrightAdapter:
    platform = "1688"

    @staticmethod
    def matches(url: str) -> bool:
        host = url.split("/")[2] if "://" in url else ""
        return host == "1688.com" or host.endswith(".1688.com")

    async def fetch(self, url: str) -> RawProduct:
        if not get_settings().live_mode:
            raise RuntimeError("LIVE_MODE=0: 真实抓取被禁止")
        html = await asyncio.to_thread(self._fetch_sync, url)
        return parse_product_html(html, url)

    def _fetch_sync(self, url: str) -> str:
        from playwright.sync_api import sync_playwright

        s = get_settings()
        state = Path(s.playwright_storage_state)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                storage_state=str(state) if state.exists() else None,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            html = page.content()
            ctx.storage_state(path=str(state))
            browser.close()
        return html
```

- [ ] **Step 6: 实现** `src/openoctopus/login.py`（扫码登录持久化）

```python
import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="openoctopus-login")
    parser.add_argument("--url", default="https://www.1688.com")
    args = parser.parse_args()

    from openoctopus.config import get_settings

    state = Path(get_settings().playwright_storage_state)
    state.parent.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(args.url)
        print("请在浏览器中完成登录（扫码），然后回到终端按回车…")
        input()
        ctx.storage_state(path=str(state))
        browser.close()
    print(f"登录态已保存到 {state}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 通过 + lint + Commit**

Run: `uv run pytest tests/collector -v && uv run playwright install chromium && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: collector with playwright adapter and html fallback parsing"
```

---

### Task 4: 文案翻译模块（LLM）

**Files:**
- Create: `src/openoctopus/content/__init__.py`, `src/openoctopus/content/translators.py`
- Test: `tests/content/test_translate.py`

**Interfaces:**
- Consumes: `RawProduct`, `TranslatedContent`
- Produces: `LLMContentTranslator(client, model)`；`async translate(raw: RawProduct) -> TranslatedContent`。`client` 为任意带 `chat.completions.create(model, messages, response_format)` 的对象（openai.AsyncOpenAI 兼容）

- [ ] **Step 1: 写失败测试** `tests/content/test_translate.py`

```python
import json

from openoctopus.content.translators import LLMContentTranslator
from openoctopus.models import RawProduct


class FakeCompletions:
    async def create(self, **kw):
        self.kw = kw
        content = json.dumps({"title_ru": "Термос из нержавеющей стали 304",
                              "bullets_ru": ["Большой объём"],
                              "description_ru": "Портативный термос."})
        msg = type("M", (), {"content": content})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


async def test_translate():
    c = LLMContentTranslator(FakeClient(), model="test-model")
    raw = RawProduct(source_url="u", platform="1688", title_zh="不锈钢保温杯",
                     bullets_zh=["大容量"], description_zh="便携水杯")
    out = await c.translate(raw)
    assert out.title_ru.startswith("Термос")
    assert out.model == "test-model"


def test_prompt_mentions_ozon():
    from openoctopus.content.translators import SYSTEM_PROMPT
    assert "Ozon" in SYSTEM_PROMPT and "JSON" in SYSTEM_PROMPT
```

- [ ] **Step 2: 运行确认失败** → Run: `uv run pytest tests/content -v` → Expected: FAIL

- [ ] **Step 3: 实现** `src/openoctopus/content/translators.py`

```python
import json

from openoctopus.models import RawProduct, TranslatedContent

SYSTEM_PROMPT = (
    "You localize Chinese e-commerce listings for the Russian marketplace Ozon. "
    "Translate to natural Russian buyer-facing copy. Rewrite the title so the most "
    "searchable keywords come first (max 120 chars). Keep bullet points concise. "
    'Respond with strict JSON: {"title_ru": str, "bullets_ru": [str], "description_ru": str}'
)


class LLMContentTranslator:
    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    async def translate(self, raw: RawProduct) -> TranslatedContent:
        user = json.dumps({
            "title": raw.title_zh,
            "bullets": raw.bullets_zh,
            "description": raw.description_zh,
            "sku_options": [{k: v for k, v in s.props.items()} for s in raw.skus],
        }, ensure_ascii=False)
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content)
        return TranslatedContent(**data, model=self.model)
```

- [ ] **Step 4: 通过 + lint + Commit**

Run: `uv run pytest tests/content -v && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: llm content translator for ru localization"
```

### Task 5: 图片渲染基元（bbox 内抹字 + 重绘俄语）

**Files:**
- Create: `src/openoctopus/image/__init__.py`, `src/openoctopus/image/render.py`
- Test: `tests/image/test_render.py`

**Interfaces:**
- Consumes: `TextBox`
- Produces:
  - `erase_boxes(img: PIL.Image, boxes: list[TextBox]) -> PIL.Image`（cv2.inpaint，仅框内）
  - `draw_translations(img: PIL.Image, boxes: list[TextBox], font_path: str) -> PIL.Image`（按原区主色自适应字号渲染 ru_text）
  - `translate_image_bytes(data: bytes, boxes: list[TextBox], font_path: str) -> bytes`

- [ ] **Step 1: 写失败测试** `tests/image/test_render.py`

```python
from io import BytesIO

from PIL import Image

from openoctopus.image.render import draw_translations, erase_boxes, translate_image_bytes
from openoctopus.models import TextBox


def make_img() -> Image.Image:
    img = Image.new("RGB", (200, 100), (240, 240, 240))
    for x in range(20, 180):
        for y in range(40, 60):
            img.putpixel((x, y), (10, 10, 10))
    return img


def test_erase_only_inside_box():
    img = erase_boxes(make_img(), [TextBox(x=20, y=40, w=160, h=20, zh_text="", ru_text="")])
    assert sum(img.getpixel((100, 50))) > 600
    assert sum(img.getpixel((10, 10))) == 720


def test_draw_translations_changes_box():
    base = make_img()
    erased = erase_boxes(base.copy(), [])
    out = draw_translations(erased, [TextBox(x=20, y=40, w=160, h=20, zh_text="保温杯", ru_text="Термос")],
                            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    hist_a = erased.crop((20, 40, 180, 60)).tobytes()
    hist_b = out.crop((20, 40, 180, 60)).tobytes()
    assert hist_a != hist_b


def test_translate_image_bytes_roundtrip():
    buf = BytesIO()
    make_img().save(buf, "PNG")
    data = translate_image_bytes(buf.getvalue(),
                                 [TextBox(x=20, y=40, w=160, h=20, zh_text="杯", ru_text="Чашка")],
                                 "/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    assert Image.open(BytesIO(data)).size == (200, 100)
```

- [ ] **Step 2: 运行确认失败** → Run: `uv run pytest tests/image -v` → Expected: FAIL

- [ ] **Step 3: 实现** `src/openoctopus/image/render.py`

```python
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from openoctopus.models import TextBox


def _dominant_color(img: Image.Image, b: TextBox) -> tuple[int, int, int]:
    region = np.array(img.crop((b.x, b.y, b.x + b.w, b.y + b.h))).reshape(-1, 3)
    dark = region[region.sum(axis=1) < 380]
    px = dark if len(dark) else region
    return tuple(int(c) for c in px.mean(axis=0))


def erase_boxes(img: Image.Image, boxes: list[TextBox]) -> Image.Image:
    arr = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    mask = np.zeros(arr.shape[:2], np.uint8)
    for b in boxes:
        mask[max(0, b.y):b.y + b.h, max(0, b.x):b.x + b.w] = 255
    if boxes:
        arr = cv2.inpaint(arr, mask, 5, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))


def _fit_font(draw, text, box_w, box_h, font_path):
    lo, hi = 8, max(8, box_h)
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        f = ImageFont.truetype(font_path, mid)
        w = draw.textlength(text, font=f)
        if w <= box_w * 1.05:
            best = f
            lo = mid + 1
        else:
            hi = mid - 1
    return best or ImageFont.truetype(font_path, 8)


def draw_translations(img: Image.Image, boxes: list[TextBox], font_path: str) -> Image.Image:
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    for b in boxes:
        if not b.ru_text:
            continue
        color = _dominant_color(out, b)
        f = _fit_font(d, b.ru_text, b.w, b.h, font_path)
        tw = d.textlength(b.ru_text, font=f)
        x = b.x + max(0, (b.w - tw) // 2)
        asc, desc = f.getmetrics()
        y = b.y + max(0, (b.h - (asc + desc)) // 2)
        d.text((x, y), b.ru_text, font=f, fill=color)
    return out


def translate_image_bytes(data: bytes, boxes: list[TextBox], font_path: str) -> bytes:
    img = Image.open(__import__("io").BytesIO(data)).convert("RGB")
    colors = {id(b): _dominant_color(img, b) for b in boxes}
    erased = erase_boxes(img, boxes)
    out = draw_translations(erased, boxes, font_path)
    buf = __import__("io").BytesIO()
    out.save(buf, "PNG")
    _ = colors
    return buf.getvalue()
```

注意：`_dominant_color` 必须在 `erase_boxes` 之前的原图上取样（上面 `translate_image_bytes` 中先算颜色再抹除；`draw_translations` 内部对已抹除图取样仅为独立调用时的回退）。

- [ ] **Step 4: 通过 + lint + Commit**

Run: `uv run pytest tests/image -v && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: bbox-scoped text erase and russian re-render primitives"
```

---

### Task 6: VLM 检测 + R2 存储 + 图片翻译管线

**Files:**
- Create: `src/openoctopus/image/detect.py`, `src/openoctopus/image/pipeline.py`, `src/openoctopus/storage/__init__.py`, `src/openoctopus/storage/r2.py`
- Test: `tests/image/test_detect.py`, `tests/storage/test_r2.py`

**Interfaces:**
- Consumes: Task4 的 client 形态、Task5 渲染函数、Settings
- Produces:
  - `detect_and_translate(client, model, image_bytes: bytes) -> list[TextBox]`
  - `R2Storage(s3_client, bucket: str, public_base: str)`；`put(key: str, data: bytes, mime: str) -> str`；`make_r2(settings) -> R2Storage | None`（未配置返回 None）
  - `VlmPipelineTranslator(client, model, storage, font_path, http)`；`async translate(image_url: str, key_hint: str) -> str`（返回公网 URL；无文字时原样返回源 URL）

- [ ] **Step 1: 写失败测试** `tests/image/test_detect.py`

```python
import json

from openoctopus.image.detect import detect_and_translate


class FakeVisionCompletions:
    async def create(self, **kw):
        boxes = {"boxes": [{"x": 1, "y": 2, "w": 3, "h": 4, "zh_text": "保温", "ru_text": "Термос"}]}
        msg = type("M", (), {"content": json.dumps(boxes)})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


class FakeChat:
    def __init__(self):
        self.completions = FakeVisionCompletions()


class FakeClient:
    def __init__(self):
        self.chat = FakeChat()


async def test_detect_returns_boxes():
    boxes = await detect_and_translate(FakeClient(), "m", b"img")
    assert boxes[0].ru_text == "Термос"
    assert (boxes[0].x, boxes[0].w) == (1, 3)
```

`tests/storage/test_r2.py`:

```python
from openoctopus.storage.r2 import R2Storage, make_r2
from openoctopus.config import Settings


class FakeS3:
    def put_object(self, **kw):
        self.kw = kw


def test_put_returns_public_url():
    s3 = FakeS3()
    r2 = R2Storage(s3, "mybucket", "https://cdn.example.com")
    url = r2.put("images/1.png", b"data", mime="image/png")
    assert url == "https://cdn.example.com/images/1.png"
    assert s3.kw["Bucket"] == "mybucket" and s3.kw["ContentType"] == "image/png"


def test_make_r2_none_when_unconfigured():
    assert make_r2(Settings(_env_file=None, r2_bucket="")) is None
```

- [ ] **Step 2: 运行确认失败** → Run: `uv run pytest tests/image tests/storage -v` → Expected: FAIL

- [ ] **Step 3: 实现** `src/openoctopus/image/detect.py`

```python
import base64
import json

from openoctopus.models import TextBox

DETECT_PROMPT = (
    "Locate ALL Chinese text in this product image. For each region give integer "
    "bbox (x,y,w,h from top-left), the original zh_text and its Russian translation "
    "ru_text suited for e-commerce. Include prices as-is converted to format "
    '"Цена: <число> юаней". Respond strict JSON: {"boxes": [...]}'
)


async def detect_and_translate(client, model: str, image_bytes: bytes) -> list[TextBox]:
    b64 = base64.b64encode(image_bytes).decode()
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": DETECT_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    data = json.loads(resp.choices[0].message.content)
    return [TextBox(**b) for b in data.get("boxes", [])]
```

- [ ] **Step 4: 实现** `src/openoctopus/storage/r2.py`

```python
import boto3

from openoctopus.config import Settings


class R2Storage:
    def __init__(self, s3_client, bucket: str, public_base: str):
        self.s3 = s3_client
        self.bucket = bucket
        self.public_base = public_base.rstrip("/")

    def put(self, key: str, data: bytes, mime: str = "image/png") -> str:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=mime)
        return f"{self.public_base}/{key}"


def make_r2(settings: Settings) -> R2Storage | None:
    if not (settings.r2_bucket and settings.r2_access_key_id and settings.r2_public_base_url):
        return None
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
    )
    return R2Storage(s3, settings.r2_bucket, settings.r2_public_base_url)
```

- [ ] **Step 5: 实现** `src/openoctopus/image/pipeline.py`

```python
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
```

- [ ] **Step 6: 通过 + lint + Commit**

Run: `uv run pytest tests/image tests/storage -v && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: vlm image translation pipeline with r2 storage"
```

### Task 7: Ozon 客户端 + 类目同步 + LLM 映射建议

**Files:**
- Create: `src/openoctopus/ozon/__init__.py`, `src/openoctopus/ozon/paths.py`, `src/openoctopus/ozon/client.py`, `src/openoctopus/category/__init__.py`, `src/openoctopus/category/sync.py`, `src/openoctopus/category/suggest.py`
- Test: `tests/ozon/test_client.py`, `tests/category/test_suggest.py`

**Interfaces:**
- Consumes: Settings（OZON_*）、httpx.AsyncClient、Task4 的 LLM client 形态
- Produces:
  - `PATHS` 常量 dict；`OzonClient(http, client_id, api_key)`：
    - `async category_tree(language="RU") -> dict`
    - `async category_attributes(category_id: int) -> list[dict]`
    - `async import_products(items: list[dict]) -> dict`
    - `async import_task_info(task_id: int) -> dict`
    - 鉴权头：`Client-Id` / `Api-Key`，BASE=`https://api-seller.ozon.ru`
  - `flatten_tree(node: dict) -> list[tuple[str, str, str]]`（id, parent_id, title）
  - `sync_categories(ozon: OzonClient, conn) -> int`（写入 ozon_categories，返回条数）
  - `pick_category(client, model, conn, raw, translated) -> str`（category_id）
  - `fill_attributes(client, model, ozon, category_id, raw, translated) -> list[dict]`

**实现时核对项：** `paths.py` 中的路径版本号对照官方文档确认一次；类目树接口返回结构以响应 fixture 为准。

- [ ] **Step 1: 写失败测试** `tests/ozon/test_client.py`

```python
import json

import httpx

from openoctopus.ozon.client import OzonClient


def make_ozon(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api-seller.ozon.ru")
    return OzonClient(http, "cid", "key")


async def test_import_products_sends_auth_and_items():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = (request.headers.get("Client-Id"), request.headers.get("Api-Key"))
        return httpx.Response(200, json={"result": {"task_id": 7}})

    ozon = make_ozon(handler)
    out = await ozon.import_products([{"offer_id": "1"}])
    await ozon.http.aclose()
    assert out["result"]["task_id"] == 7
    assert seen["auth"] == ("cid", "key")
    assert "/import" in seen["path"]


async def test_category_tree_flatten():
    tree = {"result": [{"category_id": 1, "category_name": "Дом", "childs": [
        {"category_id": 2, "category_name": "Посуда", "type_name": "Термос"}]}]}
    ozon = make_ozon(lambda req: httpx.Response(200, json=json.loads(json.dumps(tree))))
    rows = []
    from openoctopus.category.sync import flatten_tree
    for top in tree["result"]:
        rows += flatten_tree(top)
    assert ("2", "1", "Посуда") in rows
```

`tests/category/test_suggest.py`:

```python
import json

from openoctopus.category.suggest import fill_attributes, pick_category


class FakeMsg:
    def __init__(self, c):
        self.content = c


class FakeResp:
    def __init__(self, c):
        self.choices = [type("C", (), {"message": FakeMsg(c)})()]


class SeqLLM:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw["messages"])
        return FakeResp(self.replies[len(self.calls) - 1])


class Wrap:
    def __init__(self, comp):
        self.chat = type("Chat", (), {"completions": comp})()


async def test_pick_and_fill():
    llm = SeqLLM([json.dumps({"category_id": "42"}),
                  json.dumps({"attributes": [{"id": 85, "value": "Термос"}]})])
    cat_id = await pick_category(Wrap(llm), "m", [], None, None)
    assert cat_id == "42"
    attrs = await fill_attributes(Wrap(llm), "m", None, 42, None, None)
    assert attrs == [{"id": 85, "value": "Термос"}]
```

- [ ] **Step 2: 运行确认失败** → Run: `uv run pytest tests/ozon tests/category -v` → Expected: FAIL

- [ ] **Step 3: 实现** `src/openoctopus/ozon/paths.py` 与 `client.py`

```python
# paths.py —— 版本对照 https://docs.ozon.ru/api/seller 核实后如需变更只改这里
PATHS = {
    "category_tree": "/v3/category/tree",
    "category_attributes": "/v4/category/attribute",
    "import": "/v4/product/import",
    "import_info": "/v1/product/import/task/info",
}
```

```python
# client.py
import httpx

from openoctopus.ozon.paths import PATHS

BASE_URL = "https://api-seller.ozon.ru"


class OzonClient:
    def __init__(self, http: httpx.AsyncClient, client_id: str, api_key: str):
        self.http = http
        self.headers = {"Client-Id": client_id, "Api-Key": api_key}

    async def _post(self, path: str, payload: dict | None = None) -> dict:
        r = await self.http.post(path, json=payload or {}, headers=self.headers)
        r.raise_for_status()
        return r.json()

    async def category_tree(self, language: str = "RU") -> dict:
        return await self._post(PATHS["category_tree"], {"language": language})

    async def category_attributes(self, category_id: int) -> list[dict]:
        out = await self._post(PATHS["category_attributes"], {"description_category_id": category_id,
                                                              "language": "RU"})
        return out.get("result", [])

    async def import_products(self, items: list[dict]) -> dict:
        return await self._post(PATHS["import"], {"items": items})

    async def import_task_info(self, task_id: int) -> dict:
        return await self._post(PATHS["import_info"], {"task_id": task_id})
```

- [ ] **Step 4: 实现** `src/openoctopus/category/sync.py` 与 `suggest.py`

```python
# sync.py
def flatten_tree(node: dict) -> list[tuple[str, str, str]]:
    rows = [(str(node["category_id"]), str(node.get("parent_id", "") or ""),
             node.get("category_name", ""))]
    for ch in node.get("childs", []) or []:
        if "category_id" in ch:
            rows += flatten_tree(ch)
    return rows


def sync_categories(ozon, conn) -> int:
    tree = conn.execute("SELECT * FROM ozon_categories").fetchone()
    data = _tree_cache(conn)
    n = 0
    for top in data.get("result", []):
        for cid, pid, title in flatten_tree(top):
            conn.execute(
                "INSERT INTO ozon_categories(id,parent_id,title) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id, title=excluded.title",
                (cid, pid, title))
            n += 1
    conn.commit()
    return n


def _tree_cache(conn):
    from openoctopus.jobs.context import get_tree_payload
    return get_tree_payload(conn)


# suggest.py
import json

PICK_PROMPT = (
    "Given a product description and candidate Ozon categories, pick the best "
    'category_id. Respond strict JSON: {"category_id": "<id>"}'
)

ATTRS_PROMPT = (
    "Map this product to the given Ozon attribute schema values in Russian. "
    'Respond strict JSON: {"attributes": [{"id": int, "value": str, '
    '"dictionary_value_id": int|null}]}'
)


async def pick_category(client, model, candidates, raw, translated) -> str:
    user = json.dumps({"product": translated.model_dump(),
                       "candidates": candidates[:300]}, ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": PICK_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.0)
    return str(json.loads(resp.choices[0].message.content)["category_id"])


async def fill_attributes(client, model, schema_items, raw, translated) -> list[dict]:
    user = json.dumps({"schema": schema_items,
                       "product_zh": raw.model_dump() if raw else {},
                       "product_ru": translated.model_dump() if translated else {}},
                      ensure_ascii=False)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": ATTRS_PROMPT},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.0)
    return json.loads(resp.choices[0].message.content)["attributes"]
```

注：`sync_categories` 里 `_tree_cache` 的真实拉取在 Task 9 的 context 中注入（测试用内存库直接预填 ozon_categories 即可测 flatten/sync 循环体）；若嫌绕，可将拉取改为参数 `sync_categories(ozon, conn, tree: dict)`——按此签名实现，调用方负责 `await ozon.category_tree()`。

- [ ] **Step 5: 通过 + lint + Commit**

Run: `uv run pytest tests/ozon tests/category -v && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: ozon seller api client with category sync and llm mapping"
```

---

### Task 8: 上架 payload 构建（golden file 测试）

**Files:**
- Create: `src/openoctopus/listing/__init__.py`, `src/openoctopus/listing/builder.py`
- Test: `tests/listing/test_builder.py`, fixture: `tests/fixtures/golden_import.json`

**Interfaces:**
- Consumes: TranslatedContent、images 表的公网 URL 列表、category_mappings 的 attributes
- Produces: `build_import_payload(title_ru: str, description_ru: str, offer_id: str, price_rub: float, category_id: int, attributes: list[dict], image_urls: list[str]) -> dict`

payload 形状：

```python
{
  "items": [{
    "offer_id": offer_id,
    "name": title_ru[:200],
    "description": description_ru,
    "description_category_id": category_id,
    "price": str(price_rub),
    "currency_code": "RUB",
    "images": image_urls,
    "attributes": [{"complex_id": 0, "id": int(a["id"]),
                    "values": ([{"dictionary_value_id": a["dictionary_value_id"]}]
                               if a.get("dictionary_value_id") else [{"value": a["value"]}])}
                   for a in attributes],
  }]
}
```

- [ ] **Step 1: 写失败测试** `tests/listing/test_builder.py`

```python
import json
from pathlib import Path

from openoctopus.listing.builder import build_import_payload

GOLDEN = json.loads((Path(__file__).parent.parent / "fixtures" / "golden_import.json").read_text())


def test_build_matches_golden():
    payload = build_import_payload(
        title_ru="Термос из нержавеющей стали",
        description_ru="Портативный термос.",
        offer_id="oo-1",
        price_rub=150.0,
        category_id=42,
        attributes=[{"id": 85, "value": "Сталь"},
                    {"id": 90, "value": "", "dictionary_value_id": 123}],
        image_urls=["https://cdn.example.com/a.png"],
    )
    assert payload == GOLDEN


def test_name_truncated():
    p = build_import_payload("Б" * 500, "d", "of", 10.0, 1, [], [])
    assert len(p["items"][0]["name"]) == 200
```

fixture `golden_import.json`：

```json
{
  "items": [{
    "offer_id": "oo-1",
    "name": "Термос из нержавеющей стали",
    "description": "Портативный термос.",
    "description_category_id": 42,
    "price": "150.0",
    "currency_code": "RUB",
    "images": ["https://cdn.example.com/a.png"],
    "attributes": [
      {"complex_id": 0, "id": 85, "values": [{"value": "Сталь"}]},
      {"complex_id": 0, "id": 90, "values": [{"dictionary_value_id": 123}]}
    ]
  }]
}
```

- [ ] **Step 2: 运行确认失败** → Run: `uv run pytest tests/listing -v` → Expected: FAIL

- [ ] **Step 3: 实现** `builder.py`（照上面"payload 形状"逐字段实现，函数纯同步）

- [ ] **Step 4: 通过 + lint + Commit**

Run: `uv run pytest tests/listing -v && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: ozon import payload builder with golden test"
```

### Task 9: 任务队列 + AppContext + 三个业务 handler

**Files:**
- Create: `src/openoctopus/jobs/__init__.py`, `src/openoctopus/jobs/context.py`, `src/openoctopus/jobs/queue.py`, `src/openoctopus/jobs/handlers.py`
- Test: `tests/jobs/test_queue.py`, `tests/jobs/test_handlers.py`

**Interfaces:**
- Consumes: 前面全部模块
- Produces:
  - `AppContext`（dataclass）：settings, db_path, adapters(list), llm_client, content_translator, image_translator, ozon, storage；`build_context(settings) -> AppContext`
  - `HANDLERS: dict[str, Handler]`，Handler = `async (ctx, payload: dict) -> None`；键：collect / generate / publish
  - `enqueue(conn, type_: str, payload: dict) -> int`
  - `JobRunner(conn, handlers, ctx).run_once() -> bool`；`run_forever(poll_interval=2.0)`；失败重试至多 3 次后置 failed 并记录 error

- [ ] **Step 1: 写失败测试** `tests/jobs/test_queue.py`

```python
import pytest

from openoctopus.db import get_conn, init_db
from openoctopus.jobs.queue import JobRunner, enqueue


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "j.db")
    init_db(p)
    return get_conn(p)


async def test_done_and_retry_paths(db):
    calls = []

    async def ok(ctx, payload):
        calls.append(payload["n"])

    async def boom(ctx, payload):
        raise RuntimeError("x")

    enqueue(db, "ok", {"n": 1})
    enqueue(db, "boom", {})
    r = JobRunner(db, {"ok": ok, "boom": boom})
    await r.run_once()
    await r.run_once()
    assert calls == [1]
    st = {row["type"]: row["status"] for row in db.execute("SELECT * FROM jobs")}
    assert st["ok"] == "done"
    assert st["boom"] == "queued"

    for i in range(2):
        db.execute("UPDATE jobs SET status='queued' WHERE type='boom'")
        db.commit()
        await r.run_once()
    db.execute("UPDATE jobs SET status='queued' WHERE type='boom' AND retries<3")
    db.commit()
    await r.run_once()
    row = db.execute("SELECT * FROM jobs WHERE type='boom'").fetchone()
    assert row["status"] == "failed" and row["error"] == "x" and row["retries"] == 3
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/jobs -v`
Expected: FAIL (no module openoctopus.jobs)

- [ ] **Step 3: 实现** `src/openoctopus/jobs/queue.py`

```python
import asyncio
import json

MAX_RETRIES = 3


def enqueue(conn, type_: str, payload: dict) -> int:
    cur = conn.execute("INSERT INTO jobs(type, payload_json) VALUES(?,?)",
                       (type_, json.dumps(payload)))
    conn.commit()
    return cur.lastrowid


class JobRunner:
    def __init__(self, conn, handlers: dict, ctx=None):
        self.conn = conn
        self.handlers = handlers
        self.ctx = ctx

    async def run_once(self) -> bool:
        row = self.conn.execute(
            "SELECT id, type, payload_json, retries FROM jobs "
            "WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return False
        self.conn.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
        self.conn.commit()
        try:
            await self.handlers[row["type"]](self.ctx, json.loads(row["payload_json"]))
            self.conn.execute("UPDATE jobs SET status='done' WHERE id=?", (row["id"],))
        except Exception as e:
            retries = row["retries"] + 1
            status = "failed" if retries >= MAX_RETRIES else "queued"
            self.conn.execute("UPDATE jobs SET status=?, retries=?, error=? WHERE id=?",
                              (status, retries, str(e), row["id"]))
        self.conn.commit()
        return True

    async def run_forever(self, poll_interval: float = 2.0):
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(poll_interval)
```

- [ ] **Step 4: 队列测试通过**

Run: `uv run pytest tests/jobs/test_queue.py -v`
Expected: PASS

- [ ] **Step 5: 写 handler 失败测试** `tests/jobs/test_handlers.py`

```python
import json
from types import SimpleNamespace

from openoctopus.db import get_conn, init_db
from openoctopus.jobs.handlers import handle_collect

SNAPSHOT = {
    "source_url": "https://detail.1688.com/offer/1.html", "platform": "1688",
    "title_zh": "保温杯", "bullets_zh": ["大容量"], "description_zh": "好杯子",
    "price_cny": 12.5,
    "main_images": ["https://img/main1.jpg"],
    "detail_images": ["https://img/d1.jpg"], "skus": [],
}


class FakeAdapter:
    platform = "1688"

    @staticmethod
    def matches(url):
        return True

    async def fetch(self, url):
        from openoctopus.models import RawProduct
        return RawProduct(**SNAPSHOT)


def make_ctx(tmp_path):
    db_path = str(tmp_path / "h.db")
    init_db(db_path)
    return SimpleNamespace(db_path=db_path, adapters=[FakeAdapter()], settings=None)


async def test_collect_persists_and_enqueues_generate(tmp_path):
    ctx = make_ctx(tmp_path)
    conn = get_conn(ctx.db_path)
    conn.execute(
        "INSERT INTO products(id, source_url, platform, status) "
        "VALUES(1, 'https://detail.1688.com/offer/1.html', '1688', 'new')")
    conn.commit()

    await handle_collect(ctx, {"product_id": 1})

    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "collected"
    kinds = sorted(r["kind"] for r in conn.execute(
        "SELECT kind FROM images WHERE product_id=1").fetchall())
    assert kinds == ["detail", "main"]
    job = conn.execute("SELECT * FROM jobs WHERE type='generate'").fetchone()
    assert json.loads(job["payload_json"]) == {"product_id": 1}
```

- [ ] **Step 6: 实现** `src/openoctopus/jobs/context.py` 与 `handlers.py`

context.py：

```python
from dataclasses import dataclass, field

import httpx
from openai import AsyncOpenAI

from openoctopus.collector.adapters import A1688PlaywrightAdapter
from openoctopus.config import Settings
from openoctopus.content.translators import LLMContentTranslator
from openoctopus.db import init_db
from openoctopus.image.pipeline import VlmPipelineTranslator
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
    llm = AsyncOpenAI(base_url=settings.openrouter_base_url,
                      api_key=settings.openrouter_api_key or "missing")
    ctx.llm_client = llm
    ctx.content_translator = LLMContentTranslator(llm, settings.content_model)
    ctx.storage = make_r2(settings)
    ctx.image_translator = VlmPipelineTranslator(
        llm, settings.image_model, ctx.storage, settings.font_path,
        httpx.AsyncClient(timeout=60))
    ctx.ozon = OzonClient(httpx.AsyncClient(base_url=BASE_URL, timeout=60),
                          settings.ozon_client_id, settings.ozon_api_key)
    return ctx
```

handlers.py（三个 handler + HANDLERS 映射）：

```python
import asyncio
import json

from openoctopus.category.suggest import fill_attributes, pick_category
from openoctopus.jobs.queue import enqueue
from openoctopus.listing.builder import build_import_payload
from openoctopus.models import RawProduct


async def handle_collect(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    prod = conn.execute("SELECT * FROM products WHERE id=?",
                        (payload["product_id"],)).fetchone()
    adapter = next(a for a in ctx.adapters if a.matches(prod["source_url"]))
    raw = await adapter.fetch(prod["source_url"])
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(?,?)",
                 (prod["id"], raw.model_dump_json()))
    for u in raw.main_images:
        conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(?,'main',?)",
                     (prod["id"], u))
    for u in raw.detail_images:
        conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(?,'detail',?)",
                     (prod["id"], u))
    conn.execute("UPDATE products SET status='collected', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 (prod["id"],))
    conn.commit()
    enqueue(conn, "generate", {"product_id": prod["id"]})


def upsert_translation(conn, pid, field_, zh, ru, model=""):
    conn.execute(
        "INSERT INTO translations(product_id, field, zh, ru, model) VALUES(?,?,?,?,?) "
        "ON CONFLICT(product_id, field) DO UPDATE SET zh=excluded.zh, ru=excluded.ru, "
        "model=excluded.model", (pid, field_, zh, ru, model))


async def handle_generate(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    s = ctx.settings
    conn = get_conn(ctx.db_path)
    pid = payload["product_id"]
    snap = conn.execute("SELECT raw_json FROM source_snapshots WHERE product_id=? ORDER BY id DESC",
                        (pid,)).fetchone()
    raw = RawProduct(**json.loads(snap["raw_json"]))

    tc = await ctx.content_translator.translate(raw)
    upsert_translation(conn, pid, "title", raw.title_zh, tc.title_ru, tc.model)
    upsert_translation(conn, pid, "bullets", "\n".join(raw.bullets_zh),
                       "\n".join(tc.bullets_ru), tc.model)
    upsert_translation(conn, pid, "description", raw.description_zh, tc.description_ru, tc.model)

    for row in conn.execute("SELECT id, kind, source_url FROM images "
                            "WHERE product_id=? AND status='pending'", (pid,)).fetchall():
        key_hint = f"products/{pid}/{row['kind']}-{row['id']}"
        url = await ctx.image_translator.translate(row["source_url"], key_hint)
        conn.execute("UPDATE images SET translated_url=?, status='uploaded' WHERE id=?",
                     (url, row["id"]))

    candidates = [{"id": r["id"], "title": r["title"]}
                  for r in conn.execute("SELECT id, title FROM ozon_categories LIMIT 300")]
    cat_id = await pick_category(ctx.llm_client, s.content_model, candidates, raw, tc)
    schema_items = await ctx.ozon.category_attributes(int(cat_id)) if s.live_mode else []
    attrs = await fill_attributes(ctx.llm_client, s.content_model, schema_items, raw, tc)
    conn.execute(
        "INSERT INTO category_mappings(product_id, ozon_category_id, attributes_json) VALUES(?,?,?) "
        "ON CONFLICT(product_id) DO UPDATE SET ozon_category_id=excluded.ozon_category_id, "
        "attributes_json=excluded.attributes_json, human_confirmed=0",
        (pid, cat_id, json.dumps(attrs, ensure_ascii=False)))

    price = conn.execute("SELECT price_rub FROM products WHERE id=?", (pid,)).fetchone()["price_rub"]
    if price is None:
        conn.execute("UPDATE products SET price_rub=? WHERE id=?",
                     (round(raw.price_cny * s.price_cny_to_rub), pid))
    conn.execute("UPDATE products SET status='review', updated_at=CURRENT_TIMESTAMP WHERE id=?", (pid,))
    conn.commit()


async def handle_publish(ctx, payload: dict) -> None:
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    pid = payload["product_id"]
    m = conn.execute("SELECT * FROM category_mappings WHERE product_id=?", (pid,)).fetchone()
    if not m or not m["human_confirmed"]:
        raise RuntimeError("类目与属性未经人工确认，禁止发布")
    t = {r["field"]: r["ru"] for r in conn.execute(
        "SELECT field, ru FROM translations WHERE product_id=?", (pid,))}
    main_urls = [r["translated_url"] or r["source_url"] for r in conn.execute(
        "SELECT kind, translated_url, source_url FROM images WHERE product_id=? AND kind='main' ORDER BY id",
        (pid,))]
    price = conn.execute("SELECT price_rub FROM products WHERE id=?", (pid,)).fetchone()["price_rub"]

    items = build_import_payload(
        title_ru=t["title"], description_ru=t.get("description", ""),
        offer_id=str(pid), price_rub=float(price or 0),
        category_id=int(m["ozon_category_id"]),
        attributes=json.loads(m["attributes_json"]), image_urls=main_urls)

    result = await ctx.ozon.import_products(items)
    task_id = result.get("result", {}).get("task_id")
    conn.execute("INSERT INTO listings(product_id, import_task_id) VALUES(?,?)", (pid, str(task_id)))
    conn.commit()

    status_text, err, ozon_pid = "", "", ""
    for _ in range(12):
        await asyncio.sleep(5)
        info = await ctx.ozon.import_task_info(task_id)
        rows = info.get("result", {}).get("items", [])
        if rows:
            status_text = str(rows[0].get("status", ""))
            ozon_pid = str(rows[0].get("product_id", "") or "")
            if status_text == "failed":
                err = json.dumps(rows[0].get("errors", []), ensure_ascii=False)
                break
            if status_text in ("exported", "imported"):
                break
    conn.execute("UPDATE listings SET result_json=? WHERE product_id=?",
                 (json.dumps({"status": status_text, "error": err}, ensure_ascii=False), pid))
    final = "listed" if status_text in ("exported", "imported") else "failed"
    conn.execute("UPDATE products SET status=?, ozon_product_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 (final, ozon_pid or None, pid))
    conn.commit()


HANDLERS = {"collect": handle_collect, "generate": handle_generate, "publish": handle_publish}
```

注：`handle_publish` 中 `import_task_info` 返回结构与状态枚举（exported/imported/failed）实现时对照 Ozon 文档核对一次；轮询间隔与次数（5s × 12 次）可按实际调整。

- [ ] **Step 7: 通过 + lint + Commit**

Run: `uv run pytest tests/jobs -v && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: job queue with collect/generate/publish handlers and app context"
```

### Task 10: Web 工作台（看板 + 草稿人审 + HTML 导入）

**Files:**
- Create: `src/openoctopus/web/__init__.py`, `src/openoctopus/web/app.py`, `src/openoctopus/web/templates/kanban.html`, `src/openoctopus/web/templates/review.html`
- Modify: `src/openoctopus/jobs/handlers.py`（追加 `collect_from_html`）
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes: AppContext、JobRunner+HANDLERS、parse_product_html
- Produces:
  - `collect_from_html(ctx, file_bytes: bytes, filename: str) -> int`（返回 product_id；创建 collected 商品+快照+图片行并排队 generate）
  - `create_app(ctx, run_worker: bool = True) -> FastAPI`
  - 路由：`GET /` 看板；`POST /products`(url)；`POST /products/import-html`(文件)；`GET /products/{id}` 人审页；`POST /products/{id}/edit`（保存译文/价格/类目属性，human_confirmed=1）；`POST /products/{id}/approve`→publishing+job(publish)；`POST /products/{id}/regenerate`→generating+job(generate)；`POST /jobs/{id}/retry`

- [ ] **Step 1: 写失败测试** `tests/web/test_app.py`

```python
from io import BytesIO
from types import SimpleNamespace

from fastapi.testclient import TestClient

from openoctopus.config import Settings
from openoctopus.db import get_conn, init_db
from openoctopus.web.app import create_app

PAGE = ("<html><head><meta property='og:title' content='测试杯'></head><body>"
        "<div class='price'>¥5</div><div class='content-detail'></div></body></html>")


def make_client(tmp_path):
    db_path = str(tmp_path / "w.db")
    init_db(db_path)
    ctx = SimpleNamespace(settings=Settings(_env_file=None), db_path=db_path)
    return TestClient(create_app(ctx, run_worker=False)), db_path


def test_submit_url_enqueues_collect(tmp_path):
    c, db_path = make_client(tmp_path)
    r = c.post("/products", data={"url": "https://detail.1688.com/offer/9.html"},
               follow_redirects=False)
    assert r.status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT count(*) FROM products").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='collect'").fetchone()[0] == 1


def test_kanban_shows_groups(tmp_path):
    c, _ = make_client(tmp_path)
    c.post("/products", data={"url": "https://detail.1688.com/offer/9.html"})
    assert "待处理" in c.get("/").text


def test_import_html(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    assert c.post("/products/import-html", files=files, follow_redirects=False).status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT status FROM products").fetchone()["status"] == "collected"
    assert conn.execute("SELECT count(*) FROM jobs WHERE type='generate'").fetchone()[0] == 1


def test_review_and_edit_flow(tmp_path):
    c, db_path = make_client(tmp_path)
    files = {"file": ("p.html", BytesIO(PAGE.encode()), "text/html")}
    c.post("/products/import-html", files=files)
    assert c.get("/products/1").status_code == 200
    r = c.post("/products/1/edit", data={
        "title_ru": "Термос", "description_ru": "Описание", "price_rub": "150",
        "ozon_category_id": "42", "attributes_json": "[{\"id\":85,\"value\":\"Сталь\"}]",
    }, follow_redirects=False)
    assert r.status_code == 303
    conn = get_conn(db_path)
    assert conn.execute("SELECT human_confirmed FROM category_mappings "
                        "WHERE product_id=1").fetchone()["human_confirmed"] == 1
    assert c.post("/products/1/approve", follow_redirects=False).status_code == 303
    assert conn.execute("SELECT status FROM products WHERE id=1").fetchone()["status"] == "publishing"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/web -v`
Expected: FAIL (no module openoctopus.web)

- [ ] **Step 3: 实现** `collect_from_html`（追加到 handlers.py）

```python
def collect_from_html(ctx, file_bytes: bytes, filename: str) -> int:
    from openoctopus.collector.html_parse import parse_product_html
    from openoctopus.db import get_conn

    conn = get_conn(ctx.db_path)
    rp = parse_product_html(file_bytes.decode("utf-8", "ignore"), f"upload:{filename}")
    cur = conn.execute(
        "INSERT INTO products(source_url, platform, status) VALUES(?, '1688', 'collected')",
        (rp.source_url,))
    pid = cur.lastrowid
    conn.execute("INSERT INTO source_snapshots(product_id, raw_json) VALUES(?,?)",
                 (pid, rp.model_dump_json()))
    for u in rp.main_images:
        conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(?,'main',?)", (pid, u))
    for u in rp.detail_images:
        conn.execute("INSERT INTO images(product_id, kind, source_url) VALUES(?,'detail',?)", (pid, u))
    conn.commit()
    enqueue(conn, "generate", {"product_id": pid})
    return pid
```

- [ ] **Step 4: 实现** `web/app.py`

```python
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from openoctopus.db import get_conn, init_db
from openoctopus.jobs.handlers import HANDLERS, collect_from_html, upsert_translation
from openoctopus.jobs.queue import JobRunner, enqueue

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATUS_GROUPS = [("new", "待处理"), ("collected", "已采集"), ("generating", "生成中"),
                 ("review", "待审"), ("publishing", "发布中"), ("listed", "已上架"),
                 ("failed", "失败")]


def create_app(ctx, run_worker: bool = True) -> FastAPI:
    init_db(ctx.db_path)
    app = FastAPI()
    runner = JobRunner(get_conn(ctx.db_path), HANDLERS, ctx)

    @app.on_event("startup")
    async def _start():
        if run_worker:
            import asyncio
            app.state.worker = asyncio.create_task(runner.run_forever())

    @app.on_event("shutdown")
    async def _stop():
        w = getattr(app.state, "worker", None)
        if w:
            w.cancel()

    @app.get("/", response_class=HTMLResponse)
    def kanban(request: Request):
        conn = get_conn(ctx.db_path)
        groups = [(label, conn.execute(
            "SELECT id, source_url FROM products WHERE status=? ORDER BY updated_at DESC",
            (st,)).fetchall()) for st, label in STATUS_GROUPS]
        return TEMPLATES.TemplateResponse(request, "kanban.html", {"groups": groups})

    @app.post("/products")
    def submit(url: str = Form(...)):
        conn = get_conn(ctx.db_path)
        cur = conn.execute(
            "INSERT INTO products(source_url, platform, status) VALUES(?, '1688', 'new')", (url,))
        conn.commit()
        enqueue(conn, "collect", {"product_id": cur.lastrowid})
        return RedirectResponse("/", status_code=303)

    @app.post("/products/import-html")
    async def import_html(file: UploadFile):
        collect_from_html(ctx, await file.read(), file.filename)
        return RedirectResponse("/", status_code=303)

    @app.get("/products/{pid}", response_class=HTMLResponse)
    def review(request: Request, pid: int):
        conn = get_conn(ctx.db_path)
        p = dict(conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
        t = {r["field"]: dict(r) for r in conn.execute(
            "SELECT field, zh, ru FROM translations WHERE product_id=?", (pid,))}
        images = conn.execute("SELECT * FROM images WHERE product_id=? ORDER BY kind, id",
                              (pid,)).fetchall()
        mapping = conn.execute("SELECT * FROM category_mappings WHERE product_id=?", (pid,)).fetchone()
        cats = conn.execute("SELECT id, title FROM ozon_categories ORDER BY title LIMIT 500").fetchall()
        return TEMPLATES.TemplateResponse(request, "review.html",
                                          {"p": p, "t": t, "images": images,
                                           "mapping": mapping, "cats": cats})

    @app.post("/products/{pid}/edit")
    def edit(pid: int, title_ru: str = Form(...), description_ru: str = Form(...),
             price_rub: float = Form(...), ozon_category_id: str = Form(...),
             attributes_json: str = Form("{}")):
        import json as _json
        conn = get_conn(ctx.db_path)
        upsert_translation(conn, pid, "title", "", title_ru)
        upsert_translation(conn, pid, "description", "", description_ru)
        conn.execute("UPDATE products SET price_rub=? WHERE id=?", (price_rub, pid))
        conn.execute(
            "INSERT INTO category_mappings(product_id, ozon_category_id, attributes_json, human_confirmed)"
            " VALUES(?,?,?,1) ON CONFLICT(product_id) DO UPDATE SET "
            "ozon_category_id=excluded.ozon_category_id, attributes_json=excluded.attributes_json,"
            " human_confirmed=1", (pid, ozon_category_id, _json.loads(attributes_json) and attributes_json))
        conn.commit()
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/products/{pid}/approve")
    def approve(pid: int):
        conn = get_conn(ctx.db_path)
        conn.execute("UPDATE products SET status='publishing' WHERE id=?", (pid,))
        conn.commit()
        enqueue(conn, "publish", {"product_id": pid})
        return RedirectResponse("/", status_code=303)

    @app.post("/products/{pid}/regenerate")
    def regenerate(pid: int):
        conn = get_conn(ctx.db_path)
        conn.execute("UPDATE products SET status='generating' WHERE id=?", (pid,))
        conn.commit()
        enqueue(conn, "generate", {"product_id": pid})
        return RedirectResponse(f"/products/{pid}", status_code=303)

    @app.post("/jobs/{jid}/retry")
    def retry(jid: int):
        conn = get_conn(ctx.db_path)
        conn.execute("UPDATE jobs SET status='queued', error=NULL WHERE id=?", (jid,))
        conn.commit()
        return RedirectResponse("/", status_code=303)

    return app
```

注：edit 中 `_json.loads(...) and attributes_json` 写法仅为校验 JSON 合法性后原样存库；实现时可改为 try/except 校验。

- [ ] **Step 5: 实现模板** `kanban.html`

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>OpenOctopus</title>
<style>
 body{font-family:sans-serif;margin:24px}
 .cols{display:flex;gap:16px;flex-wrap:wrap}
 .col{flex:1;min-width:160px;background:#f4f4f4;border-radius:8px;padding:12px}
 .card{background:#fff;border-radius:6px;padding:8px;margin-top:8px;font-size:13px}
 form{margin:12px 0}
</style></head><body>
<h1>OpenOctopus 搬运工作台</h1>
<form method="post" action="/products">
  <input name="url" size="50" placeholder="粘贴 1688 商品链接">
  <button>采集</button>
</form>
<form method="post" action="/products/import-html" enctype="multipart/form-data">
  <input type="file" name="file" accept=".html">
  <button>导入 HTML 兜底</button>
</form>
<div class="cols">
{% for label, items in groups %}
  <div class="col"><strong>{{ label }} ({{ items|length }})</strong>
  {% for it in items %}
    <div class="card">
      <a href="/products/{{ it['id'] }}">#{{ it['id'] }}</a><br>
      {{ it['source_url'][:40] }}
    </div>
  {% endfor %}
  </div>
{% endfor %}
</div>
</body></html>
```

模板 `review.html`：表单字段与 `/edit` 参数一致——title_ru、description_ru、price_rub、ozon_category_id（datalist 从 cats 渲染）、attributes_json(textarea)，下方展示 zh 原文对照与图片（source vs translated）两列 `<img>`，附「保存」「提交上架」(approve)、「重新生成」(regenerate) 按钮。骨架同上（charset/style 一致），无需 JS。

- [ ] **Step 6: 通过 + lint + Commit**

Run: `uv run pytest tests/web -v && uv run ruff check .`
Expected: PASS

```bash
git add -A && git commit -m "feat: web workbench with kanban and human review flow"
```

### Task 11: 启动入口 + README + AGENTS.md 收尾

**Files:**
- Create: `src/openoctopus/__main__.py`
- Modify: `README.md`, `AGENTS.md`

**Interfaces:**
- Produces:
  - `uv run python -m openoctopus serve`：初始化 DB、build_context、启动 FastAPI（lifespan 内含 worker）
  - `uv run python -m openoctopus login`：转发到 `openoctopus.login.main()`

- [ ] **Step 1: 实现** `src/openoctopus/__main__.py`

```python
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="openoctopus")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("login")
    args = parser.parse_args()

    if args.cmd == "login":
        from openoctopus.login import main as login_main
        login_main()
        return

    import uvicorn

    from openoctopus.config import get_settings
    from openoctopus.web.app import create_app
    from openoctopus.jobs.context import build_context

    settings = get_settings()
    app = create_app(build_context(settings), run_worker=True)
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 全量回归**

Run: `uv run pytest -v && uv run ruff check .`
Expected: 全部 PASS，无 lint 错误

- [ ] **Step 3: 更新 README.md**

```markdown
# OpenOctopus

1688 → Ozon 商品搬运流水线（自用）：采集 → 俄语翻译（文案+图片）→ 类目映射 → 人审 → 官方 API 上架。

## 快速开始

​```bash
uv sync
uv run playwright install chromium
cp .env.example .env   # 填入密钥与 R2 配置
uv run python -m openoctopus login   # 首次：扫码登录 1688
uv run python -m openoctopus serve   # http://127.0.0.1:8765
​```

设计文档见 `docs/superpowers/specs/`。
```

（注意：写入时把 `​```bash` 换成正常的三反引号代码围栏。）

- [ ] **Step 4: 更新 AGENTS.md**

把「Repo 状态」小节替换为真实命令：

```markdown
## Repo 状态
- Python 项目（uv 管理），src 布局包名 `openoctopus`
- 测试：`uv run pytest -v`（单测全 mock，真实外部调用由 `LIVE_MODE=1` 门控）
- Lint：`uv run ruff check .`（提交前必须通过）
- 本地运行：`uv run python -m openoctopus serve` → http://127.0.0.1:8765
- 设计/计划文档：`docs/superpowers/specs/` 与 `docs/superpowers/plans/`
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: cli entrypoint, readme and agents guide"
git push
```

---

## Self-Review 记录（计划完成时逐项核对）

1. **Spec 覆盖对照**
   - §4.1 collector → Task 3；§4.2 content → Task 4；§4.3 image → Task 5+6（Aliyun 延后为已声明决策）；§4.4 category → Task 7；§4.5 listing → Task 7(client)+Task 8(builder)+Task 9(publish handler)；§4.6 web → Task 10；§3 架构(worker/queue) → Task 9；状态机 → Task 2 schema + handlers；定价规则(price_rub 默认汇率换算+人审可改) → Task 2 字段 + Task 9 generate/edit；错误处理(重试3次/失败列/retry路由) → Task 9 queue + Task 10 retry；测试策略(fixture/golden/mock/live门控) → 各任务 + Global Constraints
2. **占位符扫描**：无 TBD/TODO；所有代码步骤含完整代码；Ozon 接口版本号与 import_task_info 返回结构两处标注了「实现时对照文档核实」——这是外部依赖事实核查点，不是实现空缺
3. **类型一致性抽查**：`enqueue(conn,type_,payload)` / `JobRunner(conn,handlers,ctx)` / `upsert_translation(conn,pid,field,zh,ru,model="")` / `parse_product_html(html,source_url)` / `detect_and_translate(client,model,image_bytes)` / `VlmPipelineTranslator.translate(image_url,key_hint)` / `build_import_payload(title_ru,description_ru,offer_id,price_rub,category_id,attributes,image_urls)` 在定义处与调用处签名一致






