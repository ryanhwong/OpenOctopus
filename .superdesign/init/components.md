# components.md — shared UI primitives (FULL source)

There is no component library: primitives are CSS classes in `base.html` + Jinja markup
patterns reused across pages. Below is each primitive with its real CSS and its canonical
markup, so a design can reproduce them 1:1.

---

## Card — `.card`
The universal content container. White surface, 1px gray-200 border, 12px radius, 20px padding.
Hierarchy between stacked cards is created **only** by repeated `style="margin-bottom:20px"`
inline on each `<section class="card">`.

```css
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:20px}
```

```html
<section class="card" aria-label="颜色变体" style="margin-bottom:20px">
  <h2 style="margin-top:0">颜色变体</h2>
</section>
```

---

## Buttons — `.btn` + 5 variants
Solid indigo (primary), solid emerald (CTA — reserved for 提交上架 only), outline (ghost),
outline-danger (destructive secondary), plus `disabled` (opacity .6) and `:focus-visible` ring.
No icon support, no loading state, no sizes other than the default 40px and the ad-hoc
`min-height:26/28/32px` inline overrides used for secondary actions.

```css
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;
  min-height:40px;padding:8px 18px;border-radius:var(--radius-s);border:1px solid transparent;
  font-size:14px;font-weight:600;cursor:pointer;text-decoration:none;
  transition:background-color .18s ease,color .18s ease,border-color .18s ease}
.btn-primary{background:var(--primary);color:#fff}
.btn-primary:hover{background:var(--primary-dark)}
.btn-cta{background:var(--cta);color:#fff}
.btn-cta:hover{background:var(--cta-dark)}
.btn-ghost{background:var(--surface);border-color:var(--border);color:var(--text)}
.btn-ghost:hover{border-color:var(--primary);color:var(--primary)}
.btn-danger-ghost{background:var(--surface);border-color:var(--border);color:var(--danger)}
.btn-danger-ghost:hover{border-color:var(--danger)}
.btn:disabled{opacity:.6;cursor:not-allowed}
```

```html
<button class="btn btn-primary" type="submit">保存草稿</button>
<button class="btn btn-cta" type="submit">提交上架</button>
<button class="btn btn-ghost" type="submit">重新生成候选</button>
<button class="btn btn-ghost" style="min-height:32px;padding:2px 12px">重新生成候选</button>
```

---

## Status pill — `.pill` + 7 pipeline-status variants
Inline, 12px/600, fully rounded, `white-space:nowrap`. Variant class is derived from the
product status string: `pill-{{ status }}` where status ∈
`new · collected · generating · review · publishing · listed · failed`.

```css
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.pill-new{background:#eef0f4;color:var(--muted)}
.pill-collected{background:var(--info-bg);color:var(--info)}
.pill-generating{background:var(--warning-bg);color:var(--warning)}
.pill-review{background:#ffedd5;color:#c2410c}
.pill-publishing{background:var(--primary-soft);color:var(--primary-dark)}
.pill-listed{background:var(--success-bg);color:var(--success)}
.pill-failed{background:var(--danger-bg);color:var(--danger)}
```

```html
<span class="pill pill-{{ p['status'] }}">{{ p['status'] }}</span>
<span class="pill pill-new">主图</span>
```

---

## Filter chip — `.chip` (+ `.chip-active`) with inline count bubble
Used for the status filter row on `/` and for pager links. Active state = filled indigo.

```css
.chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.chip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;
  border:1px solid var(--border);background:var(--surface);color:var(--text);
  font-size:13px;font-weight:600;text-decoration:none;cursor:pointer;
  transition:border-color .18s ease,background-color .18s ease,color .18s ease}
.chip:hover{border-color:var(--primary);color:var(--primary)}
.chip-active{background:var(--primary);border-color:var(--primary);color:#fff}
.chip-active:hover{color:#fff}
.chip .count{background:transparent;color:inherit;opacity:.8;font-size:12px;padding:0}
.chip-active .count{color:#fff}
.count{background:var(--primary-soft);color:var(--primary-dark);border-radius:999px;
  font-size:12px;padding:0 9px;font-weight:700}
```

```html
<a class="chip {% if status == st %}chip-active{% endif %}" href="/?status={{ st }}"
   {% if status == st %}aria-current="page"{% endif %}>{{ label }}
  <span class="count">{{ counts[st] }}</span></a>
```

---

## Product card — `.pcard` (checkbox + thumb + 2-line title + meta)
The `/` grid unit. 44px square thumb (falls back to `#id` on primary-soft), title clamped to
2 lines, meta line with `#id · price · status label`. Hover = indigo border.
**Known weakness:** 44px thumb is too small to recognise a product.

```css
.pcard{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-s);padding:8px 10px;margin-top:8px;font-size:13px;
  transition:border-color .18s ease}
.pcard:hover{border-color:var(--primary)}
.pcard-row{display:flex;gap:10px;align-items:flex-start}
.pcard-row input[type=checkbox]{width:auto;margin:14px 0 0;flex:none}
.pcard-link{display:flex;gap:10px;flex:1;min-width:0;color:var(--text);
  text-decoration:none;cursor:pointer}
.thumb{flex:none;width:44px;height:44px;border-radius:var(--radius-s);overflow:hidden;
  background:var(--primary-soft);display:flex;align-items:center;justify-content:center;
  color:var(--primary-dark);font-weight:700}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.pinfo{min-width:0;flex:1}
.ptitle{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  font-weight:600;line-height:1.35;overflow-wrap:anywhere}
.pmeta{display:block;color:var(--muted);font-size:12px;margin-top:2px;overflow-wrap:anywhere}
```

```html
<div class="pcard">
  <div class="pcard-row">
    <input type="checkbox" name="pid" value="{{ it['id'] }}" aria-label="选中商品 #{{ it['id'] }}">
    <a class="pcard-link" href="/products/{{ it['id'] }}">
      <span class="thumb">{% if it['thumb'] %}<img src="{{ it['thumb'] }}" alt="" loading="lazy">{% else %}#{{ it['id'] }}{% endif %}</span>
      <span class="pinfo">
        <span class="ptitle">{{ it['title_ru'] or it['source_url'] }}</span>
        <span class="pmeta">#{{ it['id'] }} · {{ it['price_rub'] }} {{ currency }} · {{ status_label }}</span>
      </span>
    </a>
  </div>
</div>
```

Grid: `.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px;margin-top:12px}`

---

## Image compare card — `.imgcard` + `.pair` (source vs translated)
The core of the review page's 图片前后对比 grid. Each card: kind pill + id/status meta,
then a 2-up pair of 104px-tall `object-fit:contain` figures on white, then a "用于上架"
checkbox, then a collapsed 自定义重生成 form. Loading state = `.imgloading` with spinner;
failure = `.imgloading.err` "生成失败".

```css
.imggrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;margin-top:8px}
.imgcard{border:1px solid var(--border);border-radius:var(--radius-s);padding:10px;
  background:var(--surface);transition:border-color .18s ease}
.imgcard:hover{border-color:var(--primary)}
.imginfo{display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.pair figure{margin:0;min-width:0}
.pair img{width:100%;height:104px;object-fit:contain;background:#fff;border-radius:4px;display:block}
.pair figcaption{font-size:11px;color:var(--muted);text-align:center;margin-top:2px}
.imgcard details{margin-top:6px}
.imgcard details summary{font-size:12px}
.regen-row{display:flex;gap:6px;align-items:center;margin-top:6px}
.regen-row input{margin:0;flex:1;font-size:12px;min-height:32px;padding:4px 8px}
.regen-row .btn{min-height:32px;padding:2px 10px;white-space:nowrap;font-size:12px}
```

```html
<div class="imgcard">
  <div class="imginfo"><span class="pill pill-new">主图</span><span class="muted">#12 · done</span></div>
  <div class="pair">
    <figure><img src="/media/proxy?u=…" alt="源图 #12" loading="lazy"><figcaption>源图</figcaption></figure>
    <figure><img src="/media/proxy?u=…" alt="译文图 #12" loading="lazy"><figcaption>译文图</figcaption></figure>
  </div>
  <label style="font-weight:400;font-size:13px;display:flex;gap:6px;align-items:center;margin:6px 0 0">
    <input type="checkbox" name="sel_12" value="1" form="edit-form" checked style="width:auto;margin:0">用于上架
  </label>
  <details><summary>自定义重生成</summary>
    <form method="post" action="/products/1/images/12/regenerate">
      <div class="regen-row"><input type="text" name="prompt_override" placeholder="留空=自动翻译；如：只去左上角logo"><button class="btn btn-ghost" type="submit">重生成</button></div>
    </form>
  </details>
</div>
```

---

## Variant swatch card — `.varcard` / `.varnoimg` / `.varinfo`
38px color swatch (or index placeholder) + RU name + ZH name + meta line with price,
dictionary-match state (`✓ 词典` green / `文本` amber) and spec count.

```css
.vargrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px}
.varcard{display:flex;gap:8px;align-items:center;border:1px solid var(--border);
  border-radius:var(--radius-s);padding:6px 8px;background:var(--surface-2)}
.varcard img{width:38px;height:38px;border-radius:6px;object-fit:cover;background:#fff;flex:none}
.varnoimg{width:38px;height:38px;border-radius:6px;background:var(--primary-soft);
  color:var(--primary-dark);font-weight:700;display:flex;align-items:center;
  justify-content:center;flex:none;font-size:13px}
.varinfo{min-width:0}
.varname{font-weight:600;font-size:13px;overflow-wrap:anywhere;line-height:1.3}
.varzh{color:var(--muted);font-size:12px}
.varmeta{color:var(--muted);font-size:11px;margin-top:1px}
.varok{color:var(--success)}
.varwarn{color:var(--warning)}
```

---

## Title candidate radio — `.cand-list` / `.cand` / `.cand-style` / `.cand-text`
A radiogroup of AI-generated title candidates. Style badge above the text; clicking sets the
title input via the `form="edit-form"` attribute.

```css
.cand-list{display:flex;flex-direction:column;gap:6px;margin:6px 0 10px}
.cand{display:flex;gap:8px;align-items:flex-start;border:1px solid var(--border);
  border-radius:var(--radius-s);padding:8px 10px;background:var(--surface);cursor:pointer;
  font-weight:400;transition:border-color .18s ease}
.cand:hover{border-color:var(--primary)}
.cand input{width:auto;margin:3px 0 0;flex:none}
.cand-body{min-width:0}
.cand-style{display:inline-block;font-size:11px;font-weight:700;color:var(--primary-dark);
  background:var(--primary-soft);border-radius:999px;padding:0 8px;margin-bottom:2px}
.cand-text{display:block;font-size:13px;line-height:1.4;overflow-wrap:anywhere}
```

---

## Pricing panel — `.pricebox`
Grey well under the price input: 成本 / 汇率 / 佣金, 保本价 / 建议价 + a "填入建议价" button,
当前利润率 colored green-or-amber. 12px `--muted` with `<strong>` in `--text`, line-height 1.8.

```css
.pricebox{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-s);
  padding:8px 10px;margin:-8px 0 14px;font-size:12px;color:var(--muted);line-height:1.8}
.pricebox strong{color:var(--text)}
.pricebox .btn{min-height:26px;padding:0 8px;font-size:12px;margin-left:6px}
```

---

## Preflight checklist — `.checklist` / `.checkitem` / `.checkdot`
2–3 column responsive grid of pass/warn/fail rows. 16px colored circle with `✓ ! ×`.

```css
.checklist{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:6px 16px}
.checkitem{display:flex;gap:8px;align-items:flex-start;font-size:13px}
.checkdot{flex:none;width:16px;height:16px;border-radius:50%;margin-top:3px;display:inline-flex;
  align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#fff}
.check-ok{background:var(--success)}
.check-warn{background:var(--warning)}
.check-error{background:var(--danger)}
```

---

## Stat block — `.statrow` / `.stat` / `.statnum` / `.statlbl`
Four KPI tiles on `/dashboard`: 1px border, 8px radius, 22px indigo number over 12px gray label.

```css
.statrow{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}
.stat{border:1px solid var(--border);border-radius:var(--radius-s);padding:10px 16px;min-width:110px}
.statnum{font-size:22px;font-weight:700;color:var(--primary-dark);line-height:1.3}
.statlbl{font-size:12px;color:var(--muted)}
```

---

## Data table — `.tablewrap` + `.dtable` + `.rating`
13px table, 6/8px cell padding, 1px gray-200 rules, muted uppercase-ish headers, no zebra,
no sticky header, no row hover. `内容评级` renders as a rounded pill: good ≥100 green,
mid ≥80 amber, else red. Used by `/dashboard`, `/jobs`, `/promotions`.

```css
.dtable{width:100%;border-collapse:collapse;font-size:13px}
.dtable th{text-align:left;color:var(--muted);font-weight:600;padding:6px 8px;
  border-bottom:1px solid var(--border);white-space:nowrap}
.dtable td{padding:8px;border-top:1px solid var(--border);vertical-align:top}
.dtable a{text-decoration:none}
.dtable a:hover{text-decoration:underline}
.tablewrap{overflow-x:auto}
.rating{display:inline-block;min-width:34px;text-align:center;font-weight:700;
  border-radius:999px;padding:1px 8px;font-size:12px}
.rating-good{background:var(--success-bg);color:var(--success)}
.rating-mid{background:var(--warning-bg);color:var(--warning)}
.rating-bad{background:var(--danger-bg);color:var(--danger)}
```

---

## Page header / hero — `.hero`
Only used on the review page: 64px thumb + title-with-status-pill + source URL + price + RU title.

```css
.hero{display:flex;gap:14px;align-items:center}
.hero img{width:64px;height:64px;border-radius:var(--radius-s);object-fit:cover;
  background:var(--primary-soft);flex:none}
```

---

## Sticky action bar — `.actionbar`
Bottom-sticky white bar on the review page holding 提交上架 / 重新生成 / 删除 + a muted hint.
This is the page's primary commit surface.

```css
.actionbar{position:sticky;bottom:0;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:12px 16px;margin-top:20px;
  display:flex;gap:10px;flex-wrap:wrap;align-items:center;z-index:20}
.actionbar form{display:inline}
```

---

## Feedback & state blocks

```css
.jobrun{background:var(--warning-bg);color:var(--warning);border-radius:var(--radius-s);
  padding:6px 10px;margin-top:8px;font-size:12px}
.joberr{background:var(--danger-bg);color:var(--danger);border-radius:var(--radius-s);
  padding:8px 10px;margin-top:8px;font-size:12px}
.warnbox{border:1px solid #fca5a5;background:#fef2f2;border-radius:var(--radius-s);
  padding:8px 10px;margin:0 0 14px}
.warnline{color:var(--danger);font-size:12px}
.draftbar{display:flex;gap:8px;align-items:center;background:var(--warning-bg);color:var(--warning);
  border-radius:var(--radius-s);padding:6px 10px;margin-bottom:10px;font-size:13px}
.empty{color:var(--muted);font-size:13px;text-align:center;padding:16px 0}
.srcbox{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--radius-s);
  padding:12px 14px;margin-bottom:10px;font-size:14px}
details{margin-top:8px}
details summary{cursor:pointer;font-weight:600;font-size:13px;color:var(--muted)}
details[open] summary{margin-bottom:6px}
video{width:100%;max-height:340px;object-fit:contain;border-radius:var(--radius-s);background:#000;display:block}
.logbox{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:var(--radius-s);
  font-size:12px;overflow:auto;max-height:420px;white-space:pre-wrap;margin:0}
.rc-block{display:flex;gap:12px;border:1px solid var(--border);border-radius:var(--radius-s);
  padding:10px;margin-bottom:10px;background:var(--surface-2);align-items:flex-start}
.rc-block img{width:84px;height:84px;object-fit:cover;border-radius:6px;flex:none;background:#fff}
.rc-fields{flex:1;min-width:0}
.rc-fields input,.rc-fields textarea{margin:2px 0 8px}
.promo-thumb{width:36px;height:36px;border-radius:6px;object-fit:cover;background:var(--primary-soft);
  flex:none;display:inline-block;border:1px solid var(--border)}
```

## Layout helpers

```css
.wrap{max-width:1280px;margin:0 auto;padding:24px 24px 96px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}
@media (max-width:900px){.grid2{grid-template-columns:1fr}}
.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;justify-content:space-between}
.searchbox{display:flex;gap:6px}
.searchbox input{width:220px}
.pager{display:flex;gap:10px;align-items:center;justify-content:center;margin-top:16px}
.cols{display:flex;gap:14px;overflow-x:auto;padding-bottom:8px}
.col{flex:1;min-width:230px;background:var(--surface-2);border:1px solid var(--border);
  border-radius:var(--radius);padding:12px}
```

## Client-side behaviour already in the templates (must survive any redesign)

1. **Title candidate radio** → writes into `#f-title` and dispatches an `input` event.
2. **Character counter** `#title-count` (`aria-live="polite"`) shows `n / 150 字符`.
3. **Draft autosave** — every `input` on `#edit-form` is debounced 500ms into
   `localStorage['oo-draft-<pid>']`; on load, if the saved snapshot differs from the server
   render, `#draftbar` is revealed with 恢复 / 丢弃 buttons.
4. **Scroll memory** — `sessionStorage['oo-scroll']` restores scroll position across the 6s
   auto-refresh that runs while `status == 'generating'` or any content job is queued.
