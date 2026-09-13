# jimeng_client — 即梦（Dreamina）CLI 的极简 Python 封装

零依赖（仅标准库），**任何 Python 项目复制 `jimeng_client.py` 一个文件即可用**。
底层调用即梦官方 CLI，用本机登录态，不碰任何 Web 接口/加密。

---

## 1. 安装与登录（一次性）

```bash
# 安装官方 CLI（注意：如果本机开了代理，先 export 清掉，代理会导致下载损坏）
curl -fsSL https://jimeng.jianying.com/cli | bash

# 登录（OAuth 设备码流程，浏览器扫码一次即可；登录态全局共享）
~/.dreamina_cli/dreamina login

# 验证
~/.dreamina_cli/dreamina user_credit
```

> macOS / Linux 均可；Windows 建议 WSL。CLI 默认安装到 `~/.dreamina_cli/dreamina`。
>
> **同一台主机只需装一次、登录一次**：二进制是全局一份（`~/.dreamina_cli/dreamina`），
> 登录凭证存系统钥匙串（macOS Keychain，service=`dreamina`），所有项目共享。
> 只有 token 过期时才需要重新 `dreamina login`（仍是每台机一次，不是每项目）。
> CLI 装在别处时，用环境变量 `DREAMINA_CLI=/path/to/dreamina` 或构造参数 `JimengClient(path)`。
>
> **多项目隔离**：`--session 0` 是全局默认会话，多项目共用会共享上下文。
> 需要隔离时各自建会话：`dreamina session create --name "项目A"`，
> 调用时传 `session=<id>`（`dreamina session list` 查看）。

## 2. Python 用法

```python
from jimeng_client import JimengClient

jm = JimengClient()                      # 也可 JimengClient("/自定义路径/dreamina")

# 文生图（返回图片 URL 列表）
urls = jm.text2image("a studio photo of an orange cat wearing a red scarf",
                     ratio="1:1", resolution_type="2k")
jm.download(urls[0], "cat.png")          # URL 有时效，尽快转存

# 图生图（1-10 张输入图）
urls = jm.image2image(
    ["a.jpg", "b.jpg"],
    "把图里的中文替换成俄语，去掉英文 logo，其他保持不变",
    model_version="4.0", ratio="1:1", resolution_type="2k")
data = JimengClient.fetch(urls[0])       # 直接拿字节（可转传自己的 OSS/R2）
```

运行自带示例：

```bash
python example.py                 # 文生图
python example.py ./input.jpg     # 图生图
```

## 3. 命令行用法（任意语言）

```bash
# 图生图：注意先清代理环境变量
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  ~/.dreamina_cli/dreamina image2image \
  --images ./in.jpg \
  --prompt "Replace Chinese text with Russian, remove brand logos" \
  --model_version 4.0 --ratio 1:1 --resolution_type 2k \
  --generate_num 1 --poll 120
```

stdout 为 JSON：`gen_status == "success"` 时取 `result_json.images[0].image_url`。

## 4. API 一览

| 方法 | 说明 | 返回 |
|------|------|------|
| `text2image(prompt, **opts)` | 文生图（等待结果） | `[url, ...]` |
| `image2image(images, prompt, **opts)` | 图生图（等待结果） | `[url, ...]` |
| `submit(command, prompt, **opts)` | 异步提交 | `submit_id` |
| `query_result(submit_id)` | 查询异步结果 | `[url, ...]` |
| `user_credit()` | 账号额度 | `{total_credit, vip_level, ...}` |
| `download(url, dest)` / `fetch(url)` | 下载图片（自动绕过代理） | 路径 / `bytes` |

**通用参数**（`**opts`）：

| 参数 | 默认 | 说明 |
|------|------|------|
| `model_version` | `"4.0"` | `4.0/4.1/4.5/4.6/4.7/5.0/5.0Pro`；4.0 通常是会员免费额度 |
| `ratio` | `"1:1"` | `21:9,16:9,3:2,4:3,1:1,3:4,2:3,9:16` |
| `resolution_type` | `"2k"` | 4.x/5.0 → `2k/4k`；5.0Pro → `1.5k/2k/4k`（必填） |
| `generate_num` | `1` | 1-10 |
| `poll` | `120` | 等待秒数；异步请用 `submit()` |
| `session` | - | 会话 ID（默认 0） |
| `**extra` | - | 透传原生参数，如 `width=1024, height=1024` |

## 5. 异步任务（适合队列/批量）

```python
sid = jm.submit("image2image", "提示词", images=["a.jpg"], model_version="4.0")
# ... 稍后 ...
urls = jm.query_result(sid)
```

## 6. 常见坑（实测）

1. **代理必须绕过** —— 本模块已内置处理（CLI 子进程剔除 `*_PROXY`，下载用无代理 opener）；
   手动敲 CLI 时记得 `env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY`。
   带代理会出现请求失败、下载二进制损坏（曾下成 4.7MB 残包）。
2. **`image_url` 有时效** —— 生成成功后立刻 `download()`/`fetch()` 转存到自己的存储。
3. **分辨率/模型组合强校验** —— 组合不在支持表里直接报错（如 4.0 只支持 2k/4k）。
4. **单次最多 10 张输入图**，`generate_num` 最大 10。
5. **额度消耗** —— 每次生成扣 credits，`user_credit()` 可查；4.0 通常免费额度内。
6. **超时** —— 大分辨率/多图时给足 `poll`（默认 120s），或改用异步模式。

## 7. 在 OpenOctopus 里的完整版

本目录是**最小封装**。本项目内的完整版（`src/openoctopus/image/jimeng.py`）额外包含：
- VLM 先读图，判断"哪些中文要替换、哪些 logo 要删"，自动生成精准 edit prompt
- 无文字图片直接跳过不浪费额度
- 失败自动降级到本地 VLM 重绘管道

需要这些能力时参考主项目的 adapter 实现。
