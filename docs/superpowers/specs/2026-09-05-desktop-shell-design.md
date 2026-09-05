# 桌面壳（pywebview）设计文档

日期：2026-09-05
状态：已与用户确认方向（方案 A），待实施

## 1. 背景与目标

现有 FastAPI 网页工作台功能完整，但每次使用要开终端跑 `serve` 再手动开浏览器。目标：双击即用——原生窗口内嵌现有工作台，不开终端、不改现有界面。

成功标准：双击启动器 → 数秒内弹出 OpenOctopus 原生窗口（看板页）→ 关闭窗口即停服，无残留进程。

## 2. 已确认决策

| 决策点 | 结论 |
|---|---|
| 方案 | pywebview 原生窗口（macOS 复用系统 WebKit，不装额外引擎） |
| 界面 | 复用现有 FastAPI + Jinja 工作台，不重写 |
| 启动入口 | 新增 `python -m openoctopus desktop` 子命令 |
| 双击启动 | 附带 `scripts/OpenOctopus.command`（chmod +x 即双击运行） |
| 打包 .app | 暂缓——Playwright 浏览器外置于 `~/Library/Caches`，打包带不走，先解决一键启动 |

## 3. 模块设计

新增 `src/openoctopus/desktop.py`，单一职责：拉起服务 + 开窗 + 生命周期。

`run_desktop(host="127.0.0.1", port=8765)` 流程：
1. 后台 daemon 线程启动 uvicorn（复用 `create_app(build_context(get_settings()))`，run_worker=True）
2. 主线程轮询 `GET /` 至 200（httpx，超时 30s，失败则报错退出）
3. `webview.create_window("OpenOctopus", url, width=1280, height=900)` + `webview.start()`
4. 窗口关闭 → 进程退出，daemon 线程随之结束（无残留）

`__main__.py` 新增 `desktop` 子命令转发。

依赖：`uv add pywebview`。

## 4. 错误处理

- 端口被占用：启动前探测，8000 系端口被占则报错提示（不自动换端口，避免书签混乱）
- 服务 30s 未就绪：打印日志并退出码 1
- pywebview 未安装：`desktop` 命令给出 `uv sync` 提示而非 traceback

## 5. 测试

- 单测 mock `webview` 与 uvicorn Server：断言服务线程启动、窗口以正确 URL 创建、就绪轮询逻辑
- 真机验证（手动）：双击 `.command` → 窗口出现 → 关窗后 `lsof -i :8765` 无残留

## 6. 非目标

- pyinstaller/.app 打包、开机自启、菜单栏常驻（二期）
- Windows/Linux 适配（仅 macOS 验证）
