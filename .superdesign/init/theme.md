# theme.md — OpenOctopus design tokens

## Part 1 — Compact token summary (budget-friendly; pass THIS for token context)

**Stack reality:** no Tailwind, no CSS framework, no `@font-face`, no build step. One
hand-written `<style>` block lives inside `src/openoctopus/web/templates/base.html`
(205 lines) and every page inherits it. Server-rendered Jinja2 + plain CSS.

### Color palette (`:root` custom properties)

| Token | Value | Role |
|---|---|---|
| `--bg` | `#f5f3ff` | page background (very light indigo tint, NOT white) |
| `--surface` | `#ffffff` | cards, topbar, inputs |
| `--surface-2` | `#f8f8fc` | nested wells: kanban columns, `.pricebox`, `.srcbox`, `.varcard`, `.rc-block` |
| `--primary` | `#6366f1` | indigo-500 — links, primary button, active chip, focus ring |
| `--primary-dark` | `#4f46e5` | indigo-600 — hover state, `.statnum`, `.cand-style` text |
| `--primary-soft` | `#e0e7ff` | indigo-100 — count bubble bg, thumb placeholder, info pill bg |
| `--cta` | `#10b981` | emerald-500 — the "提交上架" action button ONLY |
| `--cta-dark` | `#059669` | emerald-600 hover |
| `--text` | `#1e1b4b` | indigo-950 body text |
| `--muted` | `#6b7280` | gray-500 secondary text, `<details>summary` |
| `--border` | `#e5e7eb` | gray-200 all hairlines |
| `--success` / `--success-bg` | `#059669` / `#d1fae5` | ok state, "已上架" pill, `.varok`, `.rating-good` |
| `--warning` / `--warning-bg` | `#b45309` / `#fef3c7` | running/warn state, "生成中" pill, `.draftbar` |
| `--danger` / `--danger-bg` | `#dc2626` / `#fee2e2` | failed state, `.warnbox` border `#fca5a5` |
| `--info` / `--info-bg` | `#4f46e5` / `#e0e7ff` | collected / publishing pill |
| placeholder text | `#9ca3af` | `input::placeholder` |
| log console | bg `#0f172a`, fg `#e2e8f0` | `.logbox` only |

Status pill mapping (one class per pipeline status):
`.pill-new` `#eef0f4`/`#6b7280` · `.pill-collected` info · `.pill-generating` warning ·
`.pill-review` `#ffedd5`/`#c2410c` · `.pill-publishing` primary-soft ·
`.pill-listed` success · `.pill-failed` danger

### Typography

- Family stack: `"Fira Sans", system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
  — **Fira Sans is declared but never loaded** (no `@font-face`, no `<link>`), so it
  always falls through to `system-ui` / PingFang SC. Reproduce the *stack*, not Fira Sans glyphs.
- Base: `15px` / `line-height 1.6`
- Scale: `h1 22px` · `h2 17px` · `h3 15px` · `.statnum 22px 700` · `.btn 14px 600` ·
  body `15px` · `.pcard 13px` · `.muted 13px` · small/meta `12px` · `.varmeta 11px` · `.cand-style 11px`
- `.brand 18px 700` (color `--primary`), `.brand small 12px 400` `--muted`
- `h1 { margin: 0 0 16px }`, `h2 { margin: 24px 0 12px }`, `h3 { margin: 20px 0 8px }`

### Spacing

Flat 2px-based scale used inline: `2 4 6 8 10 12 14 16 20 24`.
`.wrap { max-width:1280px; padding:24px 24px 96px }` — the 96px bottom padding exists so the
sticky `.actionbar` never covers the last row. `.topbar { padding:12px 24px }`.
`.card { padding:20px }`. Grid gaps: `.grid 10px`, `.imggrid 12px`, `.grid2 20px`, `.vargrid 8px`.

### Radius / shadow / border

`--radius: 12px` (cards, columns, actionbar) · `--radius-s: 8px` (buttons, inputs, thumbs,
varcards, dtable wells) · `999px` (pills, chips, count bubbles, rating) · `4px`/`.pair img`.
Shadow: exactly ONE — `--shadow: 0 1px 2px rgba(30,27,75,.05)` — and it is barely used. The
design is deliberately **flat**: hierarchy comes from `--surface` vs `--surface-2` fills and
1px `--border` hairlines, not from elevation.

### Breakpoints

One media query only: `@media (max-width:900px){ .grid2{grid-template-columns:1fr} }`.
Everything else is fluid (`auto-fill minmax()` grids, `overflow-x:auto` tables).
Target viewport is **desktop 1280–1440px**; the app is a single-operator internal tool.

### Motion

Only `transition: background-color .18s ease, color .18s ease, border-color .18s ease`
(`.btn`, `.pcard`, `.imgcard`, `.chip`, `.cand`). No transforms, no elevation animation.
The only keyframe animation is the 20px `.spinner` (`spin .8s linear infinite`) shown while an
image is still generating. `@media (prefers-reduced-motion:reduce){ *{transition:none !important} }`.

### Interaction targets & a11y

`.btn { min-height:40px }` (small inline buttons drop to 26–32px) ·
`input/textarea { padding:9px 12px; font-size:14px; width:100% }` ·
focus ring `outline:2px solid var(--primary); outline-offset:2px` on
`.btn, a, input, textarea, select, summary, .pcard-link` via `:focus-visible`.

## Part 2 — Raw source

### `:root` + base element styles (base.html lines 8–57)

```css
:root{
  --bg:#f5f3ff; --surface:#ffffff; --surface-2:#f8f8fc;
  --primary:#6366f1; --primary-dark:#4f46e5; --primary-soft:#e0e7ff;
  --cta:#10b981; --cta-dark:#059669;
  --text:#1e1b4b; --muted:#6b7280; --border:#e5e7eb;
  --success:#059669; --success-bg:#d1fae5;
  --warning:#b45309; --warning-bg:#fef3c7;
  --danger:#dc2626; --danger-bg:#fee2e2;
  --info:#4f46e5; --info-bg:#e0e7ff;
  --radius:12px; --radius-s:8px;
  --shadow:0 1px 2px rgba(30,27,75,.05);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:"Fira Sans",system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  font-size:15px;line-height:1.6}
a{color:var(--primary)}
h1{font-size:22px;margin:0 0 16px}
h2{font-size:17px;margin:24px 0 12px}
h3{font-size:15px;margin:20px 0 8px}
.muted{color:var(--muted);font-size:13px}
label{display:block;font-weight:600;font-size:13px;margin-top:4px}
input[type=text],input:not([type]),input[type=file],input[type=number],textarea,select{
  width:100%;padding:9px 12px;margin:4px 0 14px;font-size:14px;color:var(--text);
  border:1px solid var(--border);border-radius:var(--radius-s);background:var(--surface)}
input::placeholder,textarea::placeholder{color:#9ca3af}
.btn:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible,
select:focus-visible,summary:focus-visible,.pcard-link:focus-visible{
  outline:2px solid var(--primary);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none !important}}
```

### Page-local `<style>` appended at the bottom of `review.html` (loading states)

```css
.imgloading{display:flex;align-items:center;gap:8px;justify-content:center;min-height:90px;
  color:var(--muted);font-size:13px}
.imgloading.err{color:var(--danger)}
.spinner{width:20px;height:20px;border:3px solid var(--primary-soft);border-top-color:var(--primary);
  border-radius:50%;animation:spin .8s linear infinite;display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}
```
