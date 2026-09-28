# design-system.md — OpenOctopus 工作台

> Pass this file as `--context-file` on EVERY `create-design-draft` / `iterate-design-draft` /
> `execute-flow-pages` call. It is the hard constraint on visual style. Iterations explore
> **layout, hierarchy, composition and density** — never a new palette or typeface.

---

## 1. Product context

**OpenOctopus** is a single-operator internal workbench for reselling Chinese 1688 goods on
Ozon (Russia). One person runs the whole pipeline; there is no team, no multi-tenant, no
public sign-up. The interface is a **tool**, not a product surface — it is used for hours at a
stretch, on a desktop, usually in a second monitor tab.

**Pipeline (the app's spine):**
```
采集 collected → 生成中 generating → 待审 review → 发布中 publishing → 已上架 listed
                                    ↘ 失败 failed (可重试)
```
A product is *scraped* from a 1688 URL, *translated* to Russian (text + images), *enriched*
(AI title candidates, Ozon search keywords, slideshow video, rich-content detail page, color
variants), then *approved* and *published* to Ozon as one product card with many SKU variants.
After listing, the app tracks content rating, stock, promotions and batch price updates.

**Key pages:** `/` 商品列表+采集 · `/products/{pid}` 人审页（核心，12 个 POST 动作） ·
`/dashboard` 运营看板 · `/promotions` + `/promotions/{id}` 促销 · `/jobs` 任务中心

**JTBD (jobs to be done), in priority order:**
1. **审得快** — one operator must clear a queue of scraped products without missing a defect:
   wrong translation, missing Ozon category, price below break-even, missing required attribute,
   untranslated Chinese still visible in an image.
2. **不漏项** — a pre-publish checklist must make "what is still missing" unmissable.
3. **不亏钱** — price, exchange rate, commission, logistics and break-even must be visible at the
   moment of typing the price, not remembered.
4. **批量** — collect many URLs at once, batch-sync, batch-refresh metrics, batch-join promotions.
5. **看得见进度** — long AI jobs (image translation, video, rich content) run in the background;
   the UI must show what is running without blocking reading.

**Non-negotiable functional constraints (a redesign that breaks these is a failure):**
- Every control is a real `<form method="post">` to a FastAPI endpoint. No JS frameworks, no
  build step, no client-side routing, no SPA state. The design must be expressible in plain
  HTML + a little vanilla JS.
- The review page has ONE master form (`#edit-form`) that also collects fields living in other
  cards (image "用于上架" checkboxes, rich-content title/text, title-candidate radio) via the
  HTML `form="edit-form"` attribute. Layout may move, but those cross-card bindings must survive.
- The list page's grid is wrapped in a POST form for batch publish, while its search box is a
  nested GET form. Preserve both.
- Chinese is the operator's language; Russian is the *content* being produced. Content in
  Russian must never be clipped without an ellipsis affordance, and Chinese source text stays
  available as on-demand reference (`<details>`), never as a wall of text.
- Localized by convention only (no i18n layer): hardcoded Chinese labels, `lang="zh-CN"`.

---

## 2. Branding & styling (locked)

### Color
Light theme only. Background is a faint indigo tint, not pure white.

| Role | Token | Value |
|---|---|---|
| page bg | `--bg` | `#f5f3ff` |
| surface | `--surface` | `#ffffff` |
| nested well | `--surface-2` | `#f8f8fc` |
| primary / interactive | `--primary` · `--primary-dark` · `--primary-soft` | `#6366f1` · `#4f46e5` · `#e0e7ff` |
| success CTA (提交上架 only) | `--cta` · `--cta-dark` | `#10b981` · `#059669` |
| text | `--text` / `--muted` | `#1e1b4b` / `#6b7280` |
| hairline | `--border` | `#e5e7eb` |
| semantic | success / warning / danger | `#059669` / `#b45309` / `#dc2626` (+ `-bg` tints) |

**Rules:** indigo carries all interactive affordances. **Emerald is reserved for the single
"提交上架" commit action** — do not spread it to other buttons. Status colour is semantic
(green=ok/listed, amber=generating/warn, red=failed, indigo=collected/publishing, gray=new) and
must stay consistent across pills, checklist dots and rating chips. No new hues, no gradients
on surfaces, no dark mode in this scope.

### Typography
- Stack: `"Fira Sans", system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
  (Fira Sans is declared but never loaded — it renders as system UI. Keep the stack; do not
  introduce a display/serif face.)
- Base 15px / line-height 1.6. Hierarchy by weight and color, not by many sizes:
  `h1 22 · h2 17 · h3 15 · stat number 22 · button 14 · body 15 · secondary 13 · meta 12 · micro 11`.
- Labels are 13px/600. Secondary/meta text is `--muted` at 12–13px. Numbers in KPI tiles and
  prices are bold; use tabular alignment for anything in a column.

### Spacing, radius, elevation
- 2px-based spacing scale: `2 4 6 8 10 12 14 16 20 24`. Content max-width 1280px with 24px
  gutters. Cards: 12px radius / 20px padding; controls: 8px radius; chips+pills: fully rounded.
- **Flat by default:** 1px `--border` hairlines and `--surface` vs `--surface-2` fills carry the
  hierarchy. The single existing shadow is `0 1px 2px rgba(30,27,75,.05)`. Restrained elevation
  (≤2 levels, low-opacity, large blur) is acceptable for sticky bars and popovers; heavy drop
  shadows and glassmorphism are not.
- Interactive targets ≥40px for primary actions, ≥28px for inline secondary actions.

### Layout structure
- One sticky topbar (56px) + a centered 1280px content column. Page = vertical stack of
  `.card` sections separated by 20px. The review page is a two-column grid (form left, media
  right) above full-width sections. Sticky bottom action bar for the commit action.
- Data-heavy areas (rating, stock, price, SKU counts) belong in aligned tables or dense grids,
  not prose. Long lists get filters + counts + pagination.

### Motion
Transitions on `background-color` / `color` / `border-color` at `.18s ease` only. No layout or
transform animation, no entrance animations. One exception permitted: an indeterminate spinner
for in-flight AI jobs. Honor `prefers-reduced-motion: reduce` (disable all transitions).

### Icons & imagery
No icon system exists today — labels are text-only. Inline SVG line icons (1.5px stroke,
currentColor, 16/20px) are an acceptable addition for nav, status and actions. Product imagery
is real e-commerce photography: square thumbnails, `object-fit: cover` for cards and
`contain` on white for before/after comparison pairs.

---

## 3. What "better" means for this product

Ranked, because not all improvements are equal here:

1. **Scan-ability of a defect.** A reviewer must spot a wrong price, a missing category, an
   untranslated image, or a failed check *without reading prose*. Status, numbers and warnings
   need stronger visual weight than supporting text.
2. **Density with air.** The current page is a ~2000px single scroll of equal-weight cards.
   Group by task (copy → price → media → publish) and let the reviewer act without scrolling
   back and forth; keep 40px+ targets and 12–20px section rhythm.
3. **One obvious next action per section.** Each card should lead with its primary button;
   destructive and secondary actions recede.
4. **Persistent, trustworthy status.** Running jobs, unsaved drafts, and pre-publish failures
   are the three states that must never be missed.
5. **Consistency across the four smaller pages** (`/dashboard`, `/jobs`, `/promotions`,
   `/promotions/{id}`) so the redesign of `/` and the review page does not leave them orphaned.
