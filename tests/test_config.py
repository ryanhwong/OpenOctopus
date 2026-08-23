from openoctopus.config import Settings


def test_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("PRICE_CNY_TO_RUB", "13.5")
    monkeypatch.setenv("LIVE_MODE", "1")
    s = Settings()
    assert s.db_path == str(tmp_path / "t.db")
    assert s.price_cny_to_rub == 13.5
    assert s.live_mode is True


def test_defaults():
    s = Settings(_env_file=None)
    assert s.price_cny_to_rub == 12.0
    assert s.live_mode is False
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
