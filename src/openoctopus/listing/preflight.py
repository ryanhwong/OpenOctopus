"""发布前预检：汇总卡片的可发布性与风险提示。"""

from openoctopus.listing.pricing import margin_pct, price_change_pct


def preflight(*, mapping, images, title_warnings, price, advice,
              last_price_sent, stock, dims_count: int,
              unmatched_colors: int = 0, dup_colors: bool = False) -> list[dict]:
    """返回 [{"level": "ok|warn|error", "text": str}]。"""
    items: list[dict] = []

    def add(level: str, text: str) -> None:
        items.append({"level": level, "text": text})

    if not mapping or not mapping["human_confirmed"]:
        add("error", "类目未确认：填写类目并保存草稿")
    n_main = sum(1 for i in images if i["kind"] == "main" and i["selected"])
    if n_main == 0:
        add("error", "没有选中任何主图")
    elif n_main < 8:
        add("warn", f"主图仅 {n_main} 张，建议 ≥8 张（内容评级）")
    for w in title_warnings or []:
        add("warn", f"标题：{w}")
    if dup_colors:
        add("error", "存在重复颜色值，Ozon 无法合并变体")
    if unmatched_colors > 0:
        add("warn", f"{unmatched_colors} 个颜色未匹配 Ozon 词典（将以文本提交）")
    if price and advice and advice.get("break_even_cny"):
        if price < advice["break_even_cny"]:
            add("error", f"价格低于保本价（{advice['break_even_cny']}），会亏本")
        else:
            m = margin_pct(price, advice)
            target = advice.get("target_margin_pct") or 0
            if m < target:
                add("warn", f"利润率 {m}% 低于目标 {target}%")
    elif not price:
        add("error", "价格未填写")
    ch = price_change_pct(price, last_price_sent)
    if ch is not None and abs(ch) > 25:
        add("warn", f"价格较上次发布变动 {ch}%，>25% 可能触发 Ozon 价格检疫")
    if (stock or 0) <= 0:
        add("warn", "库存为 0：上架后不可售")
    if dims_count < 4:
        add("warn", "尺寸重量未填全")
    if not items:
        add("ok", "全部检查通过")
    return items
