#!/bin/bash
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo "找不到 uv，请先安装 uv（https://docs.astral.sh/uv/）"; exit 1; }
exec uv run python -m openoctopus desktop
