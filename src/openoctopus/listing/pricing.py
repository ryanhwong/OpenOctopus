"""定价建议与护栏：保本价、建议价、利润率、改价幅度。"""


def price_advice(cost_cny: float, *, commission_pct: float, shipping_cny: float,
                 target_margin_pct: float, rate: float = 0.0) -> dict:
    """按总成本与佣金倒推保本价和建议价（币种与上架币种一致，跨境店为 CNY）。"""
    cost = max(0.0, float(cost_cny or 0))
    total = cost + max(0.0, float(shipping_cny or 0))
    fee = max(0.0, min(float(commission_pct or 0), 90.0)) / 100.0
    break_even = total / (1 - fee) if fee < 1 else total
    suggested = break_even * (1 + max(0.0, float(target_margin_pct or 0)) / 100.0)
    return {
        "cost_cny": round(cost, 2),
        "total_cost_cny": round(total, 2),
        "break_even_cny": round(break_even, 2),
        "suggested_cny": round(suggested, 2),
        "commission_pct": float(commission_pct or 0),
        "target_margin_pct": float(target_margin_pct or 0),
        "rate": rate,
    }


def margin_pct(price: float, advice: dict) -> float:
    """当前价对应的净利润率（%），相对总成本。"""
    total = float(advice.get("total_cost_cny") or 0)
    if not price or total <= 0:
        return 0.0
    net = float(price) * (1 - float(advice.get("commission_pct") or 0) / 100.0)
    return round((net - total) / total * 100.0, 1)


def price_change_pct(price: float, last: float | None) -> float | None:
    """相对上次发布价的变动幅度（%）；缺数据返回 None。"""
    try:
        p, l = float(price), float(last)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if p <= 0 or l <= 0:
        return None
    return round((p - l) / l * 100.0, 1)
