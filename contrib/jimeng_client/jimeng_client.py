"""即梦（Dreamina）官方 CLI 的最小 Python 封装。

零依赖：只用标准库。其他项目可直接复制本文件使用。

前提：
    1) 安装 CLI：curl -fsSL https://jimeng.jianying.com/cli | bash
    2) 登录一次：~/.dreamina_cli/dreamina login

用法：
    from jimeng_client import JimengClient

    jm = JimengClient()
    urls = jm.image2image("input.jpg", "把图中中文换成俄语，去掉英文 logo")
    jm.download(urls[0], "output.jpg")
    print(jm.user_credit())

注意：
    - CLI 走本机直连，运行时自动剔除代理环境变量（代理会导致失败）
    - 生成出的 image_url 有时效，请尽快下载转存
    - 每次生成消耗账号 credits（model_version="4.0" 通常是会员免费额度）
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from collections.abc import Iterable, Sequence

DEFAULT_CLI = os.path.expanduser("~/.dreamina_cli/dreamina")
INSTALL_HINT = "curl -fsSL https://jimeng.jianying.com/cli | bash && " \
               "~/.dreamina_cli/dreamina login"


class JimengError(RuntimeError):
    """CLI 调用或结果解析失败。"""


class JimengClient:
    def __init__(self, cli_path: str | None = None, timeout: int = 300):
        self.cli = cli_path or os.environ.get("DREAMINA_CLI") or DEFAULT_CLI
        if not os.path.exists(self.cli):
            raise JimengError(
                f"未找到 dreamina CLI：{self.cli}\n安装并登录：{INSTALL_HINT}")
        self.timeout = timeout

    # ---------- 底层 ----------

    @staticmethod
    def _clean_env() -> dict:
        """剔除所有 *_PROXY / all_proxy，CLI 必须直连。"""
        return {k: v for k, v in os.environ.items()
                if not k.upper().endswith("_PROXY") and k.lower() != "all_proxy"}

    def _run(self, args: Sequence[str], timeout: int | None = None) -> dict:
        try:
            proc = subprocess.run(
                [self.cli, *args], capture_output=True, text=True, check=False,
                env=self._clean_env(), timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as e:
            raise JimengError(f"dreamina 超时（{timeout or self.timeout}s）：{' '.join(args[:2])}") from e
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise JimengError(f"dreamina 退出码 {proc.returncode}：{detail}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise JimengError(f"无法解析 CLI 输出：{proc.stdout[:300]!r}") from e

    @staticmethod
    def _image_urls(data: dict) -> list[str]:
        if data.get("gen_status") != "success":
            raise JimengError(
                f"生成未成功：gen_status={data.get('gen_status')} "
                f"{data.get('fail_reason', '')}")
        images = (data.get("result_json") or {}).get("images", [])
        urls = [str(i.get("image_url")) for i in images if i.get("image_url")]
        if not urls:
            raise JimengError(f"结果里没有图片：{str(data)[:200]}")
        return urls

    @staticmethod
    def _append_extra(args: list[str], extra: dict) -> None:
        """透传附加参数，如 width=1024 -> --width 1024（键名原样，不转换下划线）。"""
        for key, value in extra.items():
            if value is None:
                continue
            args += ["--" + key, str(value)]

    @staticmethod
    def _as_list(images: str | os.PathLike | Iterable) -> list[str]:
        if isinstance(images, (str, os.PathLike)):
            return [str(images)]
        return [str(p) for p in images]

    # ---------- 生成 ----------

    def image2image(self, images, prompt: str, *, model_version: str = "4.0",
                    ratio: str = "1:1", resolution_type: str = "2k",
                    generate_num: int = 1, poll: int = 120,
                    session: int | None = None, **extra) -> list[str]:
        """图生图。images 支持单个路径或 1-10 个路径的列表。返回图片 URL 列表。

        需要异步（不等待）时请用 submit("image2image", ...)。
        """
        if poll <= 0:
            raise JimengError("poll=0 为异步模式，请改用 submit('image2image', ...) 拿 submit_id")
        paths = self._as_list(images)
        if not 1 <= len(paths) <= 10:
            raise JimengError("图片数量需为 1-10 张")
        args = ["image2image", "--images", ",".join(paths),
                "--prompt", prompt, "--model_version", model_version,
                "--ratio", ratio, "--resolution_type", resolution_type,
                "--generate_num", str(generate_num), "--poll", str(poll)]
        if session is not None:
            args += ["--session", str(session)]
        self._append_extra(args, extra)
        return self._image_urls(self._run(args))

    def text2image(self, prompt: str, *, model_version: str = "4.0",
                   ratio: str = "1:1", resolution_type: str = "2k",
                   generate_num: int = 1, poll: int = 120,
                   session: int | None = None, **extra) -> list[str]:
        """文生图。返回图片 URL 列表。需要异步时请用 submit("text2image", ...)。"""
        if poll <= 0:
            raise JimengError("poll=0 为异步模式，请改用 submit('text2image', ...) 拿 submit_id")
        args = ["text2image", "--prompt", prompt, "--model_version", model_version,
                "--ratio", ratio, "--resolution_type", resolution_type,
                "--generate_num", str(generate_num), "--poll", str(poll)]
        if session is not None:
            args += ["--session", str(session)]
        self._append_extra(args, extra)
        return self._image_urls(self._run(args))

    def submit(self, command: str, prompt: str, *, images=None,
               model_version: str = "4.0", ratio: str = "1:1",
               resolution_type: str = "2k", generate_num: int = 1, **extra) -> str:
        """异步提交（不等待），返回 submit_id。command: "image2image" / "text2image"。"""
        args = [command, "--prompt", prompt, "--model_version", model_version,
                "--ratio", ratio, "--resolution_type", resolution_type,
                "--generate_num", str(generate_num), "--poll", "0"]
        if command == "image2image":
            paths = self._as_list(images or [])
            if not 1 <= len(paths) <= 10:
                raise JimengError("image2image 需要 1-10 张图片")
            args += ["--images", ",".join(paths)]
        self._append_extra(args, extra)
        data = self._run(args)
        submit_id = data.get("submit_id") or (data.get("result_json") or {}).get("submit_id")
        if not submit_id:
            raise JimengError(f"未拿到 submit_id：{str(data)[:200]}")
        return str(submit_id)

    def query_result(self, submit_id: str) -> list[str]:
        """查询异步任务结果，返回图片 URL 列表。"""
        return self._image_urls(self._run(["query_result", f"--submit_id={submit_id}"]))

    def user_credit(self) -> dict:
        """查询账号额度：{total_credit, user_id, vip_level, ...}"""
        return self._run(["user_credit"])

    # ---------- 工具 ----------

    @staticmethod
    def download(url: str, dest: str, timeout: int = 120) -> str:
        """下载生成的图片（绕过系统代理），返回保存路径。"""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=timeout) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
        return dest

    @staticmethod
    def fetch(url: str, timeout: int = 120) -> bytes:
        """下载并返回字节（适合直接转发到自己的对象存储）。"""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=timeout) as resp:
            return resp.read()
