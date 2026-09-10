"""用 ffmpeg 从商品图生成幻灯片视频（Ozon 视频属性用）。"""

import os
import shutil
import subprocess
import sys
import tempfile

import httpx


def _ffmpeg() -> str:
    """解析 ffmpeg 绝对路径（launchd 环境无 homebrew PATH）。"""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.exists(p):
            return p
    return "ffmpeg"


def make_slideshow(image_urls: list[str], duration_per: float = 3.0,
                   max_images: int = 6) -> bytes:
    """下载图片并合成 1080x1080 幻灯片 MP4，返回字节。失败返回 b""。"""
    urls = [u for u in image_urls if u][:max_images]
    if len(urls) < 2:
        return b""
    ffmpeg = _ffmpeg()
    try:
        with tempfile.TemporaryDirectory() as td:
            imgs = []
            for i, u in enumerate(urls):
                p = os.path.join(td, f"i{i}.jpg")
                r = httpx.get(u, timeout=45, follow_redirects=True)
                r.raise_for_status()
                with open(p, "wb") as f:
                    f.write(r.content)
                imgs.append(p)
            segments = []
            for i, p in enumerate(imgs):
                seg = os.path.join(td, f"s{i}.mp4")
                subprocess.run(
                    [ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", p,
                     "-t", str(duration_per),
                     "-vf", ("scale=1080:1080:force_original_aspect_ratio=decrease,"
                             "pad=1080:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"),
                     "-c:v", "libx264", "-preset", "fast", "-crf", "25", seg],
                    check=True)
                segments.append(seg)
            lst = os.path.join(td, "list.txt")
            with open(lst, "w") as f:
                f.writelines(f"file '{s}'\n" for s in segments)
            out = os.path.join(td, "out.mp4")
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                 "-i", lst, "-c", "copy", out], check=True)
            with open(out, "rb") as f:
                return f.read()
    except Exception as e:  # noqa: BLE001
        print(f"[video] slideshow failed: {e}", file=sys.stderr)
        return b""
