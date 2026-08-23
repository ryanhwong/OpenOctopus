# OpenOctopus 设计文档：1688 → Ozon 自动搬运上架流水线

日期：2026-08-23
状态：已与用户确认设计方向，待实施

## 1. 背景与目标

为 Ozon（俄罗斯电商平台）卖家提供自用的商品搬运工具：从 1688 采集商品详情，自动完成俄语文案翻译、图片翻译、Ozon 类目属性映射，生成可人审的 listing 草稿，经确认后通过 Ozon 官方 Seller API 上架。

**成功标准**：粘贴一条 1688 链接 → 数分钟内在工作台得到翻译完整、图片已本地化的草稿 → 人审微调后一键提交 Ozon 并跟踪过审结果。

## 2. 已确认的关键决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| 定位 | 自用单账号工具 | 验证全链路价值优先；架构不背多租户复杂度 |
| 货源 | 1688 优先（Playwright 爬取为主） | 官方开放平台需企业认证+付费订购，自用不划算；浏览器自动化+登录态复用即可覆盖自用量级 |
| 自动化程度 | 自动生成 + 人审卡点 | 图片翻译无 100% 可靠全自动方案，人审是质量兜底 |
| 技术栈 | Python 全栈 | 爬虫/图像/LLM 生态最成熟 |
| 技术路线 | 混合渐进（方案 C） | 官方 API 为主爬虫兜底；图片翻译先免费 VLM 管线，付费服务做 fallback |
| 图片翻译 | VLM 管线为主（≈0 成本） | 见 §5；商品主体像素级不失真 |

**明确不做（MVP 范围外）**：拼多多适配器、订单/库存同步、多租户/SaaS 化、自动定价调价、多平台货源。

## 3. 总体架构

本机运行的单体应用：

- **FastAPI** 提供 API + 服务端渲染的人审工作台（Jinja2 + HTMX，看板式）
- **SQLite** 存全部业务数据，同时充当任务队列
- **单 worker 进程**轮询 `jobs` 表消费任务（不引入 Redis/Celery）
- **R2（Cloudflare）** 托管翻译后的图片公网 URL——因为 Ozon `product/import` 只接受图片 URL，不接受文件上传

```
粘贴1688链接 → collect job → generate job → 待审草稿
→ 工作台确认/微调 → publish job → Ozon Seller API → 轮询结果 → 完成/失败
```

## 4. 模块划分

每个模块单一职责，通过 Protocol 接口解耦，可独立测试替换。

### 4.1 `collector` — 采集
- `SourceAdapter` Protocol：`async fetch(url) -> RawProduct`（归一化结构：标题、卖点、描述、SKU 规格表、价格、主图列表、详情图列表）
- 实现：`A1688PlaywrightAdapter`（Playwright 驱动真实浏览器，扫码登录一次后 cookies 持久化到 storage_state 复用；主路径）；`HtmlFileAdapter`（解析手动保存的商品页 HTML 文件，零反爬风险兜底）
- 原始返回值整体存档至 `source_snapshots`，便于重放与排查
- 反爬对策：低频访问 + 拟人节奏；遇滑块验证时暂停并提示人工处理后重试

### 4.2 `content` — 文案翻译
- `ContentTranslator` Protocol，LLM 实现
- 标题按俄语电商搜索习惯改写（核心关键词前置），卖点/描述忠实翻译
- 每个字段记录所用模型，人工改过标记 `edited_by_human`

### 4.3 `image` — 图片翻译
接口 `ImageTranslator`，两个实现：
- **默认 `VlmPipelineTranslator`**（见 §5）
- **fallback `AliyunEcomTranslator`**（阿里云电商图片翻译，可选付费降级）

产物统一上传 R2，记录公网 URL。原图永不修改，翻译图另存。

### 4.4 `category` — 类目与属性映射
- 启动时/定期从 Ozon API 拉取类目树 + 每类目的属性 schema（含必填项、字典枚举值）缓存入库
- 生成草稿时 LLM 推荐：源品类 → Ozon 类目 + 属性取值映射
- 人审卡点上必须显式确认类目与必填属性后才允许提交

### 4.5 `listing` — 上架
- 组装 Ozon `product/import` payload（golden file 测试覆盖）
- 提交后跟踪 import task 状态，把 Ozon 的逐 item 错误（如缺必填属性）回写到对应商品展示

### 4.6 `web` — 人审工作台
- 看板列：待处理 / 生成中 / 待审 / 发布中 / 已上架 / 失败
- 草稿页：左右对照（原文 vs 译文）、图片前后对比、类目属性编辑、一键提交、失败一键重试
- 本机使用，不做登录鉴权（绑定 localhost）

## 5. 图片翻译管线（VlmPipelineTranslator）

三个子任务中 LLM 只负责"理解"，"编辑"由确定性代码完成：

1. **检测+识别+翻译（VLM 一次调用）**：输入原图，输出 JSON `[{bbox, zh_text, ru_text}]`。模型走 OpenRouter（免费额度模型即可），模型名做成配置项不写死
2. **抹除（OpenCV inpaint / LaMa）**：仅在 bbox 内抹字，框外像素零改动 → 商品主体不可能失真
3. **重绘（PIL）**：在原位置按原字号自适应渲染俄语文本（字体缩放、颜色取原文字区域主色）

约束与对策：
- OpenRouter 免费层限速（约 20 req/min、每日数百次）→ 全部调用过 worker 队列串行+退避，不追求吞吐
- 免费模型列表常变动 → 模型名配置化，调用失败自动换备用模型再降级到 Aliyun
- 复杂底纹背景抹除效果差 → 单图降级图像编辑模型（Gemini Flash Image / Qwen-Image-Edit）只修该图；仍差则标记"需人工处理"进失败列

## 6. 数据模型（SQLite）

- `products`：id、source_url、source_platform、status（状态机见 §7）、ozon_product_id、price_rub（上架价，人审页可改，默认 = price_cny × `OO_PRICE_CNY_TO_RUB`）、时间戳
- `source_snapshots`：product_id、raw_json、fetched_at（采集原始留档）
- `translations`：product_id、field（title/description/bullet/attribute）、zh、ru、model、edited_by_human
- `images`：product_id、kind(main/detail)、source_url、translated_url(R2)、status(pending/translating/uploaded/failed/needs_human)、meta_json(bbox 等)
- `category_mappings`：product_id、ozon_category_id、attributes_json、human_confirmed
- `jobs`：type(collect/generate/publish/sync_category)、payload_json、status(queued/running/done/failed)、retries、error
- `listings`：product_id、import_task_id、result_json、submitted_at

## 7. 商品状态机

```
new → collected → generating → review → publishing → listed
  (粘贴链接后)                        ↘ failed ←——————↘ (Ozon 逐 item 错误也归入 failed 并展示原因)
review 可手动改字段后重新 generate
failed 一键重试回到对应阶段（各 stage 幂等）
```

看板"待处理"列 = `new` 及排队中的 job 对应商品。

## 8. 错误处理

- 所有 stage 幂等，重复执行不产生副作用（靠 source_snapshot 与固定 id 派生路径保证）
- worker 对瞬时错误指数退避重试 3 次，超限置 failed 并入看板失败列
- 外部 API（1688/Ozon/OpenRouter/R2）错误分类：鉴权错→提示配置、限流→退避重试、业务错→原样透出到 UI
- Ozon 过审被拒信息定期拉取回填到对应 listing

## 9. 测试策略

- `collector`：用录制的 API 响应 fixture 回放测试，不打真实网络
- `listing`：payload 组装用 golden file 断言
- `image` 管线：VLM 调用 mock 固定 bbox 输出，断言抹除/重绘的图像处理正确性
- 真实外部调用统一由环境变量 `LIVE_MODE=1` 控制，CI 默认关闭

## 10. 配置与密钥（.env，已 gitignore）

`OZON_CLIENT_ID`、`OZON_API_KEY`、`OPENROUTER_API_KEY`、`R2_*`（bucket/keys/公开域名）、`IMAGE_TRANSLATE_MODEL`、`CONTENT_TRANSLATE_MODEL`、`PRICE_CNY_TO_RUB`（汇率倍率，默认 12）、`FONT_PATH`、`LIVE_MODE`

## 11. 用户前置准备清单

1. ✅ seller.ozon.ru 后台生成 `Client-Id` / `Api-Key`（已提供）
2. Cloudflare R2 建 bucket + 绑定公开访问域名
3. 首次使用运行 `uv run python -m openoctopus login` 扫码登录 1688，cookies 持久化本地
4. （可选，暂缓）阿里云电商图片翻译——VLM 管线为主时无需开通

## 12. 后续演进方向（不在本期）

- PDD / 淘宝等新 `SourceAdapter`
- 自建图像管线替换第三方依赖
- 多店铺账号管理（SaaS 区第一步）
- 订单拉单、库存同步、调价 repricer
