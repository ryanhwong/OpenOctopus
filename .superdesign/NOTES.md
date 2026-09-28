# OpenOctopus 前端改造 — 交接笔记

> 状态：**已停工（额度耗尽）**。2026-09-28 收工时的完整现场。
> 恢复方式：读本文件 → 读 `.superdesign/resume.json` → 从「下一步」继续。

## 目标

优化 **人审页 `/products/{pid}`** + **商品列表 `/`**，让界面更好看更好用。
已批准的设计边界（不要越界）：

- 后端零改动：不碰 `app.py` 路由、不碰表单 `action`/字段名 → 162 个测试必须全绿
- 不引入 npm / 框架 / 构建步骤（服务端渲染 + 手写 CSS）
- 保留无障碍：`aria-label` / `aria-current` / `focus-visible` / `prefers-reduced-motion`
- 其余 4 页（看板/任务/促销×2）不能变样 → `base.html` 的 token 只增不删
- 不做暗色模式

## 已完成

1. **仓库分析（init）**：`.superdesign/init/` 六个文件 + `.superdesign/design-system.md`
   - `theme.md` 含紧凑 token 摘要（PAYLOAD BUDGET 用这个，不要传整个 CSS）
   - `components.md` 含全部 primitive 的真实 CSS + 规范 markup
   - `layouts.md` 含 base.html 全文
2. **Superdesign project**：`9c92491a-98dc-401d-8200-ea3da73f5a47`
   画布：https://superdesign.dev/teams/9a690154-79d9-4803-9d16-5e629188d193/projects/9c92491a-98dc-401d-8200-ea3da73f5a47
3. **抽取 5 个共享组件**（布局优先）：`TopNav`（含 active 态修掉「按钮当导航」）·
   `PageHeader` · `ProductHero` · `ActionBar` · `StatusPill`
4. **真机像素参照**：Playwright 抓了 review 页（1440px 全页）与列表页，已上传为 canvas reference
   - review node `db4a00d6-749b-4afe-a1a9-f6183f2aae1e`
   - list node `185ad7a2-0938-43a2-a953-6757c0417cf6`
5. **3 个方向已生成**（每个都验证过是真实 HTML 构建，非截图偷懒），HTML 存在 `.superdesign/prompts/`：

   | 方向 | draftId | 本地 HTML |
   |---|---|---|
   | 现状复刻（基准） | `ebf77a2a-b6ad-46fc-99b1-922d7d880a92` | `baseline-review-v2.html` |
   | A 密集控制台 | `dcef0504-fff4-4a71-9804-7ba7512d9de6` | `branch-A-dense-console.html` |
   | **B 分步工作台（用户选定）** | `0fe043e6-3523-4bc1-aa78-2343d8e50bd5` | `branch-B-stepped-workbench.html` |
   | C 画廊优先 | `e8de58b6-dc9f-469d-b2d8-88b7857e92a3` | `branch-C-gallery-first.html` |

6. **`resume.json` 已把 B 设为 active**，`pendingSteps` 字段记录了待办。

## 额度

已花 **192**：5.5（废稿）+ 66（复刻）+ 120.5（三方向）。
第一次复刻失败教训：模型把整张截图当 `<img>` 塞进去交差（14 行假复刻）。
→ 已废弃。**教训：不要给复刻稿传 `--reference-id` 截图**，否则模型会走捷径；
要传就必须在 prompt 里明令「禁止嵌入截图，必须用真实 HTML 元素构建」。

## 下一步（按顺序）

### 1. 精修 B（被额度阻断，prompt 已备好）

```bash
npx --yes @superdesign/cli@latest iterate-design-draft \
  --draft-id 0fe043e6-3523-4bc1-aa78-2343d8e50bd5 --mode replace \
  -p "$(cat .superdesign/prompts/05-refine-b-selected.txt)" \
  --model gpt-5.6-sol \
  --context-file .superdesign/design-system.md \
  --context-file .superdesign/init/theme.md \
  --context-file .superdesign/init/components.md \
  --context-file src/openoctopus/web/templates/base.html \
  --context-file src/openoctopus/web/templates/review.html
```

要修的三点（读 B 的 HTML 时发现的真实缺口，不是臆测）：

1. **step 2–5 没有展开态设计** —— 只有 step 1 被渲染，媒体类步骤（视频/29 变体/31 图片）
   完全没设计。不补这块就无法照着写代码，只能自己发明。
2. **导航仍无 active 态** —— 四个链接长得一模一样，`商品` 应为 active（indigo 实心 + `aria-current="page"`）。
3. **价格数字是编的**，且与真实数据矛盾 —— 稿里写 `保本价 35.2 / 利润率 36.4%`，
   真实值是 `成本 16.8（含物流 3.4）· 汇率 12.80 · 佣金 20.0% · 保本价 19.38 · 建议价 38.9 · 利润率 60.2%`。

### 2. 从 B 派生商品列表页

`execute-flow-pages`（不要用 `create-design-draft`），继承 B 的风格与外壳。
列表页要有：状态筛选 chips（带计数）、搜索、批量同步、卡片网格、采集表单。

### 3. 落成真实代码（不需要额度，随时可做）

- 新建 `src/openoctopus/web/static/app.css`：把 base.html 里 205 行内联 `<style>` 搬出来 + 新 token/组件
- `app.py` 挂 `/static`（**唯一的非模板改动**）
- 按 B 结构重写 `review.html`：5 步步骤条、一次只展开一步、其余折叠成结果摘要行、
  右侧常驻轨道（发布前检查 + 价格概览 + 提交上架）
- 顺带修：导航 active 态、`.pcard` 缩略图 44px→更大、所有 `style="margin-bottom:20px"` 收进类
- 验证：`uv run pytest`（162）+ `uv run ruff check .` + Playwright 截图对比改前/改后
- 每次改动 commit + push

## 落地时的技术陷阱（已踩过，别再踩）

- 人审页有一个**跨卡片的主表单** `#edit-form`：图片「用于上架」勾选框、详情页 `rc_*` 字段、
  标题候选 radio 都在别的卡片里，靠 HTML `form="edit-form"` 属性绑到主表单。B 的稿子把它写成
  `<form class="hidden">` —— **实现时不能这样**，主表单必须真正包住内容，否则字段不会提交。
- 列表页整个网格包在 `POST /products/publish-batch` 里，而搜索框是嵌套的 `GET` 表单
  —— 两个行为都要保住（历史上出过嵌套 form 的 bug）。
- 生成中状态每 6 秒 `location.reload()`，靠 `sessionStorage['oo-scroll']` 恢复滚动位置
  —— 改成多步/分栏布局后要重新验证滚动恢复。
