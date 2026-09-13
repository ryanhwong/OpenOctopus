"""即梦 CLI 封装最小示例。

运行：
    python example.py                 # 文生图（不传参）
    python example.py ./input.jpg     # 图生图（传本地图）
"""

import sys

from jimeng_client import JimengClient


def main() -> None:
    jm = JimengClient()
    credit = jm.user_credit()
    print("账号额度:", credit.get("total_credit"), "| 会员等级:", credit.get("vip_level"))

    if len(sys.argv) > 1:
        src = sys.argv[1]
        print(f"\n[图生图] 处理 {src}")
        urls = jm.image2image(
            src,
            "Replace any Chinese text with Russian, remove English brand logos, "
            "keep the product, hands, background and composition unchanged")
        print("  生成 URL:", urls[0])
        jm.download(urls[0], "image2image.png")
        print("  已保存 image2image.png")
        return

    print("\n[文生图] a studio photo of an orange cat wearing a red scarf")
    urls = jm.text2image("a studio photo of an orange cat wearing a red scarf",
                         ratio="1:1", resolution_type="2k")
    print("  生成 URL:", urls[0])
    jm.download(urls[0], "text2image.png")
    print("  已保存 text2image.png")


if __name__ == "__main__":
    main()
