from service.config import AppConfig


def test_app_config_defaults_have_no_secrets():
    cfg = AppConfig.from_env(env={})
    assert cfg.fmp_api_key is None
    assert cfg.fred_api_key is None
    assert cfg.database_url == "sqlite:///./amp.db"
    assert cfg.report_storage_path == "output"


def test_app_config_reads_provided_env():
    cfg = AppConfig.from_env(env={
        "FMP_API_KEY": "abc123",
        "DATABASE_URL": "postgresql://x/y",
        "REPORT_STORAGE_PATH": "/data/reports",
    })
    assert cfg.fmp_api_key == "abc123"
    assert cfg.database_url == "postgresql://x/y"
    assert cfg.report_storage_path == "/data/reports"


def test_app_config_blank_env_value_is_none_not_empty_string():
    cfg = AppConfig.from_env(env={"FMP_API_KEY": ""})
    assert cfg.fmp_api_key is None
