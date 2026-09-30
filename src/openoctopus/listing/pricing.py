"""定价建议与护栏：保本价、建议价、加价率/利润率、改价幅度。

口径约定（重要，历史上混淆过）：
    总成本 T = 成本 + 物流；费率 f = 佣金；保本价 = T / (1 - f)
    target_margin_pct 实际是**加价率**（相对成本），不是利润率：
        建议价 = 保本价 × (1 + target_margin_pct)
    加价率与利润率只在 f = 0 时相等；f = 20% 时目标"利润率 30%"
    需要 42.9% 加价率，代码给出的建议价实际只有 18.5% 利润率。
    两者换算：加价率 = 利润率 / (1 - 利润率)
    本模块不改动任何既有算式，只把两个口径都显式暴露给界面。
"""


def price_advice(cost_cny: float, *, commission_pct: float, shipping_cny: float,
                 target_margin_pct: float, rate: float = 0.0) -> dict:
    """按总成本与佣金倒推保本价和建议价（币种与上架币种一致，跨境店为 CNY）。

    target_margin_pct 按加价率（相对成本）处理，见模块文档。
    """
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


def _net_revenue(price: float, advice: dict) -> float:
    """扣掉平台佣金后的到手金额。"""
    return float(price) * (1 - float(advice.get("commission_pct") or 0) / 100.0)


def markup_pct(price: float, advice: dict) -> float:
    """加价率（%）：(到手金额 - 总成本) / 总成本。相对成本，数值偏大。"""
    total = float(advice.get("total_cost_cny") or 0)
    if not price or total <= 0:
        return 0.0
    return round((_net_revenue(price, advice) - total) / total * 100.0, 1)


def net_margin_pct(price: float, advice: dict) -> float:
    """真实利润率（%）：(到手金额 - 总成本) / 到手金额。相对售价，通常说的利润率。"""
    total = float(advice.get("total_cost_cny") or 0)
    if not price or total <= 0:
        return 0.0
    net = _net_revenue(price, advice)
    if net <= 0:
        return 0.0
    return round((net - total) / net * 100.0, 1)


def margin_pct(price: float, advice: dict) -> float:
    """历史名，实际返回的是**加价率**。preflight 依赖此语义，请改用 markup_pct。"""
    return markup_pct(price, advice)


def price_change_pct(price: float, last: float | None) -> float | None:
    """相对上次发布价的变动幅度（%）；缺数据返回 None。"""
    try:
        p, l = float(price), float(last)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if p <= 0 or l <= 0:
        return None
    return round((p - l) / l * 100.0, 1)
