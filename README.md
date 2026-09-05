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

设计文档见 `docs/superpowers/specs/`。

## 桌面启动（macOS）

双击 `scripts/OpenOctopus.command`（首次右键→打开以绕过 Gatekeeper），或：

```bash
uv run python -m openoctopus desktop
```
