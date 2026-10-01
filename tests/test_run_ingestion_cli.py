import datetime as dt

import pandas as pd

import run_ingestion
from service.db import get_session_factory, init_db
from service.ingestion import ingest_prices


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


def test_scheduled_run_resumes_from_existing_coverage_instead_of_full_start(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/amp.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("FMP_API_KEY", "fake-key")
    universe_file = tmp_path / "universe.txt"
    universe_file.write_text("AAA\nBBB\n")

    engine = init_db(db_url)
    with get_session_factory(engine)() as s:
        for tk in ["AAA", "BBB"]:
            ingest_prices(s, pd.DataFrame({"date": [dt.date(2020, 1, 5)], "ticker": [tk],
                                           "adj_close": [10.0], "volume": [100]}), "yfinance")

    captured = {}

    def fake_build_prices_csv(universe, start, end, out_path):
        captured["prices_start"] = start
        pd.DataFrame(columns=["date", "ticker", "adj_close", "volume"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    def fake_build_macro_csv(start, end, out_path):
        captured["macro_start"] = start
        pd.DataFrame(columns=["date"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    def fake_build_fundamentals_csv(universe, api_key, out_path, period="quarter"):
        pd.DataFrame(columns=["date", "ticker"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    monkeypatch.setattr(run_ingestion.data_adapters, "build_prices_csv", fake_build_prices_csv)
    monkeypatch.setattr(run_ingestion.data_adapters, "build_macro_csv", fake_build_macro_csv)
    monkeypatch.setattr(run_ingestion.data_adapters, "build_fundamentals_csv",
                        fake_build_fundamentals_csv)

    run_ingestion.main(["--universe-file", str(universe_file)])

    assert captured["prices_start"] == "2020-01-06"
    # no macro coverage at all yet -> falls back to the --start floor, not an error
    assert captured["macro_start"] == "2015-01-01"


def test_full_backfill_flag_forces_start_despite_existing_coverage(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/amp.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("FMP_API_KEY", "fake-key")
    universe_file = tmp_path / "universe.txt"
    universe_file.write_text("AAA\n")

    engine = init_db(db_url)
    with get_session_factory(engine)() as s:
        ingest_prices(s, pd.DataFrame({"date": [dt.date(2020, 1, 5)], "ticker": ["AAA"],
                                       "adj_close": [10.0], "volume": [100]}), "yfinance")

    captured = {}

    def fake_build_prices_csv(universe, start, end, out_path):
        captured["prices_start"] = start
        pd.DataFrame(columns=["date", "ticker", "adj_close", "volume"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    def fake_build_macro_csv(start, end, out_path):
        pd.DataFrame(columns=["date"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    def fake_build_fundamentals_csv(universe, api_key, out_path, period="quarter"):
        pd.DataFrame(columns=["date", "ticker"]).to_csv(out_path, index=False)
        return pd.read_csv(out_path)

    monkeypatch.setattr(run_ingestion.data_adapters, "build_prices_csv", fake_build_prices_csv)
    monkeypatch.setattr(run_ingestion.data_adapters, "build_macro_csv", fake_build_macro_csv)
    monkeypatch.setattr(run_ingestion.data_adapters, "build_fundamentals_csv",
                        fake_build_fundamentals_csv)

    run_ingestion.main(["--universe-file", str(universe_file), "--start", "2015-01-01",
                       "--full-backfill"])

    assert captured["prices_start"] == "2015-01-01"
