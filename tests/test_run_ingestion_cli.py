import pandas as pd

import run_ingestion


def test_fundamentals_period_flag_is_passed_through(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/amp.db")
    monkeypatch.setenv("FMP_API_KEY", "fake-key")

    captured = {}

    def fake_build_prices_csv(universe, start, end, out_path):
        pd.DataFrame(columns=["date", "ticker", "adj_close", "volume"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    def fake_build_macro_csv(start, end, out_path):
        pd.DataFrame(columns=["date"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    def fake_build_fundamentals_csv(universe, api_key, out_path, period="quarter"):
        captured["period"] = period
        pd.DataFrame(columns=["date", "ticker"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    monkeypatch.setattr(run_ingestion.data_adapters, "build_prices_csv", fake_build_prices_csv)
    monkeypatch.setattr(run_ingestion.data_adapters, "build_macro_csv", fake_build_macro_csv)
    monkeypatch.setattr(run_ingestion.data_adapters, "build_fundamentals_csv",
                        fake_build_fundamentals_csv)

    run_ingestion.main(["--fundamentals-period", "annual"])

    assert captured["period"] == "annual"


def test_fundamentals_period_defaults_to_quarter(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/amp.db")
    monkeypatch.setenv("FMP_API_KEY", "fake-key")

    captured = {}

    def fake_build_prices_csv(universe, start, end, out_path):
        pd.DataFrame(columns=["date", "ticker", "adj_close", "volume"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    def fake_build_macro_csv(start, end, out_path):
        pd.DataFrame(columns=["date"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    def fake_build_fundamentals_csv(universe, api_key, out_path, period="quarter"):
        captured["period"] = period
        pd.DataFrame(columns=["date", "ticker"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    monkeypatch.setattr(run_ingestion.data_adapters, "build_prices_csv", fake_build_prices_csv)
    monkeypatch.setattr(run_ingestion.data_adapters, "build_macro_csv", fake_build_macro_csv)
    monkeypatch.setattr(run_ingestion.data_adapters, "build_fundamentals_csv",
                        fake_build_fundamentals_csv)

    run_ingestion.main([])

    assert captured["period"] == "quarter"
