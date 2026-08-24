# AGENTS.md

## Git push（重要，勿用 HTTPS）
- 本机推送走 SSH 443 通道，origin 已配置为：
  ```bash
  ssh://git@ssh.github.com:443/ryanhwong/OpenOctopus.git
  ```
- SSH key `~/.ssh/id_rsa` 已注册在 GitHub ryanhwong 账号，直接 push 即可。
- 若新仓库仍是 HTTPS remote，先切换：
  ```bash
  git remote set-url origin "ssh://git@ssh.github.com:443/ryanhwong/<仓库名>.git"
  ```
- 首次连接报 host key 确认时：加 `-o StrictHostKeyChecking=accept-new`，或先验证 `ssh -p 443 -T git@ssh.github.com`（输出 `Hi ryanhwong!` 即通）。

## Repo 状态
- Python 项目（uv 管理），src 布局包名 `openoctopus`
- 测试：`uv run pytest -v`（单测全 mock，真实外部调用由 `LIVE_MODE=1` 门控）
- Lint：`uv run ruff check .`（提交前必须通过）
- 本地运行：`uv run python -m openoctopus serve` → http://127.0.0.1:8765
- 设计/计划文档：`docs/superpowers/specs/` 与 `docs/superpowers/plans/`
