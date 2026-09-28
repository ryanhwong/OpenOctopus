# extractable-components.md — reusable component menu

Catalog of patterns worth turning into Superdesign `DraftComponent` entities so both target
pages share one visual language. Layout components first (they appear on every page).
Skip basic primitives (Button/Input/Card) — too simple to extract, better inline in drafts.

---

## TopNav
- Source: `src/openoctopus/web/templates/base.html:214` (`.topbar`)
- Category: `layout`
- Description: Sticky white topbar — brand wordmark + subtitle, 4 nav links, right-hand slot
- Extractable props: `activeItem` (string, default `"products"`, one of
  `products|dashboard|promotions|jobs`) — currently there is NO active state; this is the fix
- Hardcoded: brand text "OpenOctopus" + "1688 → Ozon 搬运工作台", nav labels
  商品/看板/促销/任务, all CSS in base.html
- Note: the right slot on the review page holds "← 返回看板"; on `/` it holds the 1688 login
  status pill + login button

## ActionBar
- Source: `src/openoctopus/web/templates/review.html:294` (`.actionbar`)
- Category: `layout`
- Description: Bottom-sticky commit bar — primary CTA + regenerate + delete + hint text
- Extractable props: `hint` (string, default `"提交前请确认译文、价格、类目与必填属性无误"`)
- Hardcoded: button labels 提交上架/重新生成/删除商品, `.btn-cta` / `.btn-danger-ghost` / `.btn-ghost`

## PageHeader
- Source: `src/openoctopus/web/templates/dashboard.html:4` + `kanban.html:33` (`.card > .toolbar`)
- Category: `layout`
- Description: Card header pattern — `<h1>` + muted one-line description, optional right-side action
- Extractable props: `title` (string), `description` (string), `actionLabel` (string, default `""`)
- Hardcoded: all typography/spacing

---

## ProductHero
- Source: `src/openoctopus/web/templates/review.html:5` (`.card > .hero`)
- Category: `layout`
- Description: 64px product thumb + `#id` + status pill + source URL + price + RU title
- Extractable props: `productId` (number), `status` (string), `price` (string), `titleRu` (string)
- Hardcoded: source-URL label text, `.hero` CSS

## ProductCard
- Source: `src/openoctopus/web/templates/kanban.html:70` (`.pcard`)
- Category: `basic`
- Description: Selectable product tile — checkbox + 44px thumb + 2-line title + meta line
- Extractable props: `selected` (boolean, default false), `thumbUrl` (string, default `""`),
  `titleRu` (string), `meta` (string), `href` (string)
- Hardcoded: `#id` thumb fallback text, all CSS

## ImageCompareCard
- Source: `src/openoctopus/web/templates/review.html:233` (`.imgcard`)
- Category: `basic`
- Description: Source-vs-translated image pair + kind pill + "用于上架" checkbox + regen form
- Extractable props: `kind` (string: 主图/详情图/色卡), `imageId` (number), `imageStatus` (string),
  `sourceUrl` (string), `translatedUrl` (string), `selected` (boolean, default true)
- Hardcoded: figcaptions 源图 / 译文图, checkbox label 用于上架, details summary 自定义重生成,
  placeholder 留空=自动翻译；如：只去左上角logo

## VariantSwatchCard
- Source: `src/openoctopus/web/templates/review.html:196` (`.varcard`)
- Category: `basic`
- Description: 38px color swatch + RU/ZH names + price + dictionary-match badge + spec count
- Extractable props: `swatchUrl` (string, default `""`), `nameRu` (string), `nameZh` (string),
  `price` (string), `matched` (boolean, default false), `combos` (number, default 1)
- Hardcoded: `✓ 词典` / `文本` labels, index placeholder when no swatch

## PreflightChecklist
- Source: `src/openoctopus/web/templates/review.html:283` (`.checklist`)
- Category: `basic`
- Description: Grid of pass/warn/fail pre-publish checks with colored 16px dots
- Extractable props: none (list-driven)
- Hardcoded: `✓` / `!` / `×` glyphs, dot colors

## StatCard
- Source: `src/openoctopus/web/templates/dashboard.html:16` (`.stat`)
- Category: `basic`
- Description: KPI tile — big indigo number over gray label
- Extractable props: `value` (string), `label` (string)
- Hardcoded: none

## StatusPill
- Source: `src/openoctopus/web/templates/base.html:59` (`.pill`)
- Category: `basic`
- Description: Pipeline-status chip with 7 semantic color variants
- Extractable props: `status` (string, default `new`) — maps to `new/collected/generating/
  review/publishing/listed/failed`
- Hardcoded: color mapping
