def test_price_advice_and_margin():
    from openoctopus.listing.pricing import margin_pct, price_advice, price_change_pct

    a = price_advice(10.0, commission_pct=20, shipping_cny=5, target_margin_pct=30)
    assert a["total_cost_cny"] == 15.0
    assert a["break_even_cny"] == 18.75
    assert abs(a["suggested_cny"] - 24.38) < 0.01
    assert margin_pct(25.0, a) == 33.3
    assert price_change_pct(30, 20) == 50.0
    assert price_change_pct(30, None) is None
    assert price_change_pct(0, 20) is None


def test_markup_and_net_margin_are_both_exposed():
    """加价率(相对成本)与真实利润率(相对售价)必须同时可读，且互不混淆。

    背景：margin_pct 返回的是加价率（除以成本），历史上被当成"利润率"显示，
    20% 佣金下两者差异巨大。本次只补齐真实利润率，不改任何定价算式。
    """
    from openoctopus.listing.pricing import markup_pct, net_margin_pct, price_advice

    a = price_advice(7.5, commission_pct=20, shipping_cny=8.0, target_margin_pct=30)
    # 真实数据：保本 19.38 / 建议 25.19（按加价率 30% 算，未改动）
    assert a["break_even_cny"] == 19.38
    assert a["suggested_cny"] == 25.19

    # 售价 75：加价率 287.1%（= UI 过去显示的"利润率"），真实利润率 74.2%
    # 两者是同一笔利润的两种看法：net_margin = markup / (1 + markup)
    assert markup_pct(75.0, a) == 287.1
    assert net_margin_pct(75.0, a) == 74.2

    # 建议价位的真实利润率只有 23.1%，兑现不了"目标利润率 30%"——这正是要暴露的
    assert net_margin_pct(a["suggested_cny"], a) == 23.1
    # 两者只在保本价附近接近；保本价处真实利润率为 0
    assert net_margin_pct(a["break_even_cny"], a) == 0.0
    # 两者同号（都取决于 net>total），但亏本时真实利润率跌幅更大
    assert markup_pct(10.0, a) < 0 and net_margin_pct(10.0, a) < 0
    assert net_margin_pct(10.0, a) < markup_pct(10.0, a)
    # 缺数据时安全返回 0，不抛异常
    assert net_margin_pct(0, a) == 0.0
    assert net_margin_pct(75.0, {}) == 0.0


def test_preflight_flags_below_break_even():
    from openoctopus.listing.preflight import preflight

    advice = {"break_even_cny": 20.0, "target_margin_pct": 30,
              "total_cost_cny": 16.0, "commission_pct": 20}
    items = preflight(mapping={"human_confirmed": 1},
                      images=[{"kind": "main", "selected": 1}] * 8,
                      title_warnings=[], price=10.0, advice=advice,
                      last_price_sent=None, stock=5, dims_count=4)
    assert any(i["level"] == "error" and "保本" in i["text"] for i in items)


def test_preflight_all_ok():
    from openoctopus.listing.preflight import preflight

    advice = {"break_even_cny": 20.0, "target_margin_pct": 30,
              "total_cost_cny": 16.0, "commission_pct": 20}
    items = preflight(mapping={"human_confirmed": 1},
                      images=[{"kind": "main", "selected": 1}] * 8,
                      title_warnings=[], price=30.0, advice=advice,
                      last_price_sent=30.0, stock=5, dims_count=4)
    assert items == [{"level": "ok", "text": "全部检查通过"}]


def test_preflight_warns_price_jump_and_dups():
    from openoctopus.listing.preflight import preflight

    advice = {"break_even_cny": 20.0, "target_margin_pct": 30,
              "total_cost_cny": 16.0, "commission_pct": 20}
    items = preflight(mapping={"human_confirmed": 1},
                      images=[{"kind": "main", "selected": 1}] * 8,
                      title_warnings=[], price=30.0, advice=advice,
                      last_price_sent=20.0, stock=5, dims_count=4,
                      unmatched_colors=2, dup_colors=True)
    joined = " ".join(i["text"] for i in items)
    assert "价格检疫" in joined
    assert "未匹配" in joined
    assert any(i["level"] == "error" for i in items)
