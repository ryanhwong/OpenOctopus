# OpenOctopus

1688 → Ozon 商品搬运流水线（自用）：采集 → 俄语翻译（文案+图片）→ 类目映射 → 人审 → 官方 API 上架。

## 快速开始

```bash
uv sync
uv run playwright install chromium
cp .env.example .env   # 填入密钥与 R2 配置
uv run python -m openoctopus login   # 首次：扫码登录 1688
uv run python -m openoctopus serve   # http://127.0.0.1:8765
```

## Chrome 采集插件（推荐采集方式）

自研插件，在你自己的浏览器里采集，零验证码：

1. Chrome 打开 `chrome://extensions` → 右上开启**开发者模式** → **加载已解压的扩展程序** → 选择本仓库 `extension/` 目录
2. 打开任意 1688 商品页，右下角点「采到 OpenOctopus」（需先启动 serve/desktop 服务）
3. 回工作台看板，商品自动进入流水线

设计文档见 `docs/superpowers/specs/`。

## 桌面启动（macOS）

双击 `scripts/OpenOctopus.command`（首次右键→打开以绕过 Gatekeeper），或：

```bash
uv run python -m openoctopus desktop
```
