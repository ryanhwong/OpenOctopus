from pathlib import Path

from openoctopus.collector.html_parse import parse_product_html

FIXTURE = Path(__file__).parent.parent / "fixtures" / "1688_page.html"


def test_parse_fixture():
    rp = parse_product_html(FIXTURE.read_text(encoding="utf-8"),
                            "https://detail.1688.com/offer/123.html")
    assert rp.platform == "1688"
    assert "保温杯" in rp.title_zh
    assert rp.price_cny == 12.5
    assert len(rp.main_images) == 2
    assert "https://cbu01.alicdn.com/img/detail1.jpg" in rp.detail_images


def test_adapter_matching():
    from openoctopus.collector.adapters import A1688PlaywrightAdapter
    from openoctopus.collector.base import get_adapter
    assert A1688PlaywrightAdapter.matches("https://detail.1688.com/offer/9.html")
    assert not A1688PlaywrightAdapter.matches("https://item.taobao.com/x.htm")
    assert isinstance(get_adapter("https://detail.1688.com/offer/9.html"), A1688PlaywrightAdapter)
