# pages.md — page dependency trees + template context variables

Jinja2 inheritance: every page depends on `base.html` (design system + shell) and nothing else.
There is no `{% include %}` between pages. "Dependencies" below = the exact `--context-file`
candidate set for designing that page.

---

## `/` — 商品列表 / 上架流水线 (TARGET 1 of 2)

- Entry: `src/openoctopus/web/templates/kanban.html` (112 lines)
- Dependencies:
  - `src/openoctopus/web/templates/kanban.html`
  - `src/openoctopus/web/templates/base.html` ← full design system + topbar (226 lines)
- Inline `<style>`/`<script>`: none (relies entirely on base.html)
- Route handler: `kanban()` in `app.py:80`

**Context variables:** `items[]` (`id`, `title_ru`, `source_url`, `price_rub`, `status`, `thumb`),
`chips[]` (status→label pairs), `counts{}` (status→count), `status`, `q`, `page`, `pages`, `total`,
`jobs{}` (pid → `{status,type,retries,error,id}`), `login` (`status`, `logged_in`, `checked_at`),
`currency`

**Structure top→bottom:**
1. Conditional alert card (扫码等待中 / 登录态验证失败) — `border-color:var(--warning|danger)`
2. Card "上架流水线": `<h1>` + muted subtitle + **batch collect form** (textarea, multi-line URLs,
   `action="/products"`) + secondary **HTML import form** (file input, `action="/products/import-html"`)
3. Outer `<form method="post" action="/products/publish-batch">` wrapping everything below
4. `.toolbar`: left = status filter `.chips` (each with count bubble, `aria-current` on active);
   right = GET search box (hidden `status` field) + emerald "批量同步选中到线上" button
5. `.grid` of `.pcard` (checkbox `name="pid"` + thumb + 2-line title + meta), plus per-card
   `.joberr` / `.jobrun` strips
6. `.empty` when no items
7. `.pager` (上一页 / N 页 · 共 M 个 / 下一页)

**Design-relevant facts:** the whole list is inside a POST form; job error strips use
`grid-column:1/-1` to span the grid; the login state lives in the topbar `nav` block, not here.

---

## `/products/{pid}` — 人审页 (TARGET 2 of 2, primary)

- Entry: `src/openoctopus/web/templates/review.html` (396 lines)
- Dependencies:
  - `src/openoctopus/web/templates/review.html`
  - `src/openoctopus/web/templates/base.html`
- Inline `<style>` (bottom of file, L308-315): `.imgloading`, `.spinner`, `@keyframes spin`
- Inline `<script>` (L317-395): title char counter, draft autosave/restore, scroll memory,
  6s auto-refresh while generating
- Route handler: `review()` in `app.py:220`

**Context variables:** `p` (product row: `id,status,source_url,price_rub,last_price_sent,stock,
length_mm,width_mm,height_mm,weight_g,video_url,rich_content`), `t` (`title.ru/zh`,
`description.ru/zh`), `hero`, `title_candidates[]` (`id,ru,style`), `keywords[]`,
`title_warnings[]`, `variants[]` (`ru,zh,swatch,price_rub,matched,combos`), `images[]`
(`id,kind,status,source_url,translated_url,selected`), `rich_blocks[]` (`img,title,text`),
`checks[]` (`level` ∈ ok/warn/error, `text`), `advice` (`cost_cny,total_cost_cny,commission_pct,
break_even_cny,suggested_cny,target_margin_pct`), `rate`, `cur_margin`, `mapping`
(`ozon_category_id,type_id,attributes_json`), `cats[]`, `r2_base`, `currency`, `content_jobs[]`,
`content_job_types[]`

**Structure top→bottom:**
1. Hero card: `.hero` 64px thumb + `<h1>` with status pill + source URL link + price + RU title
2. Empty `<form id="desc-improve-form">` (target of the AI-optimize button via `form=` attribute)
3. `.jobrun` role=status strip when content jobs are queued
4. **`.grid2` — two columns:**
   - **Left column** — card "俄语草稿": unsaved-draft bar → title candidates radiogroup →
     重新生成候选 / 抓取 Ozon 搜索词 buttons → keywords line → the master `#edit-form`:
     title input + char count + 中文原文 line + `warnbox` of title warnings → description
     label row with "AI 优化描述" button + textarea + `<details>` 中文原文 in `.srcbox` →
     price input + `.pricebox` (成本/汇率/佣金/保本价/建议价/利润率 + 填入建议价) → stock input →
     4-across dimension inputs → category input with `<datalist>` → attributes JSON textarea →
     保存草稿
   - **Right column** — card "视频与详情页": `<video>` (max-height 340px) + 生成视频 button;
     rich-content `.rc-block` list (84px thumb + title/text inputs, all bound to `#edit-form`
     via `form=` attributes) + 重新生成详情页 + `<details>` raw JSON override; then card
     "颜色变体": `.vargrid` of `.varcard` swatches
5. Full-width card "图片前后对比": toolbar (title + 生成首图信息图 button) + `.imggrid` of
   `.imgcard` (kind pill, source/translated `.pair`, 用于上架 checkbox, collapsed regen form)
6. Full-width card "发布前检查": `.checklist` of `.checkitem`
7. `.actionbar`: 提交上架 (emerald CTA) · 重新生成 · 删除商品 + muted hint

**Design-relevant facts:** this is one very long single-scroll page (~2000px+) mixing 12 POST
endpoints, a master form, and auto-refresh. The left column is a long form; the right column is
media. The sticky `.actionbar` is the only persistent commit control.

---

## `/dashboard` — 运营看板

- Entry: `src/openoctopus/web/templates/dashboard.html` (58 lines) + `base.html`
- Handler: `dashboard()` in `app.py:529`
- **Context:** `summary` (`n,skus,avg_rating,stock_total`), `rows[]`
  (`product_id,title_ru,source_url,skus,rating_min,rating_max,stock_total,available_n,reasons,refreshed_at`)
- **Structure:** one card with toolbar (`<h1>` + 刷新数据 button) + `.statrow` of 4 `.stat`
  blocks, then a card with `.tablewrap > .dtable` (7 columns: 商品/SKU/内容评级/库存/可售/问题/刷新时间).

## `/jobs` — 任务中心

- Entry: `src/openoctopus/web/templates/jobs.html` + `base.html`
- **Context:** `jobs[]` (`id,type,status,retries,product_id,error,created_at`)
- **Structure:** title card + `.dtable` (8 columns) where the status cell reuses `.pill` and the
  last cell holds a per-row 重试 form-button.

## `/promotions` — 促销列表

- Entry: `src/openoctopus/web/templates/promotions.html` (1724 bytes) + `base.html`
- **Context:** `rows[]` — activity list with `.promo-thumb` thumbnails and an 已参加 badge.
- **Structure:** title card + refresh button + table of activities linking to the detail page.

## `/promotions/{action_id}` — 促销详情

- Entry: `src/openoctopus/web/templates/promotion_detail.html` (4309 bytes) + `base.html`
- **Context:** activity info, `candidates[]` with `.promo-thumb`, profit/loss verdict vs local
  break-even price, 参加/退出 buttons.
- **Structure:** action header card + candidate list (each row = thumb + title + price + verdict).
