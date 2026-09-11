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
