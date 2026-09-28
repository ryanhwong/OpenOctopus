# routes.md — route → template map

FastAPI app factory in `src/openoctopus/web/app.py` (693 lines) using
`Jinja2Templates(directory=.../web/templates)`. Config-based routing (decorators), not
file-based. All HTML pages extend `base.html`.

## Pages (GET)

| URL | Handler (app.py) | Template | Renders |
|---|---|---|---|
| `/` | `kanban()` L80 | `kanban.html` | **商品列表 / 上架流水线** — 采集表单 + 状态筛选 chips + 商品卡片网格 + 分页 |
| `/products/{pid}` | `review()` L220 | `review.html` | **人审页** — 单商品全量编辑：文案/价格/库存/类目/视频/详情页/变体/图片对比/预检/提交 |
| `/dashboard` | `dashboard()` L529 | `dashboard.html` | 运营看板 — 4 个统计块 + 已上架商品评级/库存/可售状态表格 |
| `/promotions` | `promotions()` L550 | `promotions.html` | 促销列表 — 活动表格 + 缩略图 + 已参加徽章 |
| `/promotions/{action_id}` | `promotion_detail()` L567 | `promotion_detail.html` | 促销详情 — 活动信息 + 参加/退出按钮 + 候选商品列表（带缩略图） |
| `/jobs` | (GET registered later in file) | `jobs.html` | 任务中心 — 最近 100 条任务表格 + 失败重试 |

Query params: `/` accepts `status` (chip filter) · `q` (search title/url) · `page` (1-based).

## Form actions (POST) — the review page alone posts to 12 endpoints

| Endpoint | Purpose | Notes |
|---|---|---|
| `POST /products` | 采集 1688 链接 | textarea accepts MULTIPLE lines → batch collect |
| `POST /products/import-html` | 上传商品页 HTML 兜底 | multipart file |
| `POST /products/publish-batch` | 批量同步选中商品到线上 | checkboxes named `pid` |
| `POST /products/{pid}/edit` | 保存草稿 | **the master form** (`id="edit-form"`) — carries title, description, price, stock, dimensions, category, attributes_json, `rc_*` rich-content fields, `sel_*` image selection, and radio `title_pick` via the `form=` attribute |
| `POST /products/{pid}/approve` | 提交上架 | the green CTA |
| `POST /products/{pid}/regenerate` | 重新生成全部内容 | |
| `POST /products/{pid}/delete` | 删除商品 | `confirm()` guarded |
| `POST /products/{pid}/titles/regenerate` | 生成标题候选 | |
| `POST /products/{pid}/keywords/fetch` | 抓取 Ozon 搜索词 | |
| `POST /products/{pid}/content/video/regenerate` | 生成视频 | |
| `POST /products/{pid}/content/rich/regenerate` | 生成详情页 | |
| `POST /products/{pid}/infographic` | 生成首图信息图 | |
| `POST /products/{pid}/description/improve` | AI 优化描述 | empty form + `form="desc-improve-form"` button |
| `POST /products/{pid}/images/{imgid}/regenerate` | 单图重生成 | `prompt_override` field |
| `POST /promotions/{action_id}/activate` · `/deactivate` | 参加/退出促销 | |
| `POST /dashboard/refresh` · `/promotions/refresh` | 拉取最新数据 | |
| `POST /jobs/{jid}/retry` | 重试失败任务 | |
| `GET /media/proxy?u=<urlencoded>` | 图片代理 | used for any non-R2 image src |
| `POST /login/start` · `/login/finish` | 1688 扫码登录 | buttons live in the topbar `nav` block |

## Route → template wiring detail that matters for design

`/` renders `kanban.html` but the **whole page is wrapped in a `<form method="post"
action="/products/publish-batch">`** so every product checkbox participates in batch publish.
The inner search form uses `method="get"` and is nested — a past bug source. The design must
keep both behaviours intact (GET search + POST batch) without nested-form breakage.
