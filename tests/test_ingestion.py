import datetime as dt

import pandas as pd
import pytest

from service.db import get_session_factory, init_db
from service.db.models import DataIngestionRun, FundamentalsReported, MacroObservation, PricesDaily
from service.ingestion import (
    check_data_quality_gate,
    ingest_fundamentals,
    ingest_macro,
    ingest_prices,
)


@pytest.fixture
def session_factory():
    engine = init_db("sqlite:///:memory:")
    return get_session_factory(engine)


def _prices_df():
    return pd.DataFrame({
        "date": [dt.date(2020, 1, 1), dt.date(2020, 1, 2)] * 2,
        "ticker": ["AAA", "AAA", "BBB", "BBB"],
        "adj_close": [10.0, 10.5, 20.0, 20.5],
        "volume": [100, 110, 200, 210],
    })


def test_ingest_prices_writes_rows_with_lineage(session_factory):
    with session_factory() as s:
        result = ingest_prices(s, _prices_df(), provider="yfinance")
        assert result.status == "succeeded"
        assert result.rows_ingested == 4

        row = s.query(PricesDaily).filter_by(ticker="AAA", date=dt.date(2020, 1, 1)).one()
        assert row.provider == "yfinance"
        assert row.raw_payload_hash is not None
        assert row.retrieved_at is not None

        run = s.query(DataIngestionRun).filter_by(run_id=result.run_id).one()
        assert run.status == "succeeded"
        assert run.rows_ingested == 4


def test_ingest_prices_upserts_on_reingestion_without_duplicating(session_factory):
    with session_factory() as s:
        ingest_prices(s, _prices_df(), provider="yfinance")
        updated = _prices_df()
        updated.loc[0, "adj_close"] = 99.0
        ingest_prices(s, updated, provider="yfinance")

        rows = s.query(PricesDaily).filter_by(ticker="AAA", date=dt.date(2020, 1, 1)).all()
        assert len(rows) == 1
        assert rows[0].adj_close == 99.0


def test_ingest_prices_records_failed_run_on_bad_data(session_factory):
    bad = pd.DataFrame({"date": [dt.date(2020, 1, 1)], "ticker": ["AAA"],
                        "adj_close": ["not-a-number"], "volume": [100]})
    with session_factory() as s:
        result = ingest_prices(s, bad, provider="yfinance")
        assert result.status == "failed"
        assert result.error_message is not None

        run = s.query(DataIngestionRun).filter_by(run_id=result.run_id).one()
        assert run.status == "failed"


def test_ingest_macro_reshapes_wide_to_long(session_factory):
    macro = pd.DataFrame({
        "date": [dt.date(2020, 1, 31), dt.date(2020, 2, 29)],
        "credit_spread": [1.5, 1.6],
        "vix": [18.0, 20.0],
    })
    with session_factory() as s:
        result = ingest_macro(s, macro, provider="fred")
        assert result.rows_ingested == 4  # 2 dates x 2 series
        row = s.query(MacroObservation).filter_by(series_name="credit_spread",
                                                   observation_date=dt.date(2020, 1, 31)).one()
        assert row.value == pytest.approx(1.5)


def test_ingest_macro_skips_missing_values(session_factory):
    macro = pd.DataFrame({"date": [dt.date(2020, 1, 31)], "vix": [float("nan")]})
    with session_factory() as s:
        result = ingest_macro(s, macro, provider="fred")
        assert result.rows_ingested == 0


def test_ingest_fundamentals_derives_availability_date_from_lag(session_factory):
    fundamentals = pd.DataFrame({
        "date": [dt.date(2020, 1, 31)], "ticker": ["AAA"], "fcf_yield": [0.05],
    })
    with session_factory() as s:
        ingest_fundamentals(s, fundamentals, provider="fmp", availability_lag_days=60)
        row = s.query(FundamentalsReported).filter_by(ticker="AAA").one()
        assert row.availability_date == dt.date(2020, 1, 31) + dt.timedelta(days=60)


def test_gate_passes_with_fresh_full_coverage_data(session_factory):
    with session_factory() as s:
        today = dt.date(2020, 3, 1)
        for tk in ["AAA", "BBB"]:
            ingest_prices(s, pd.DataFrame({"date": [today], "ticker": [tk],
                                           "adj_close": [10.0], "volume": [100]}), "yfinance")
        for series in ["credit_spread", "rate_10y", "vix", "benchmark_adj_close"]:
            ingest_macro(s, pd.DataFrame({"date": [today], series: [1.0]}), "fred")
        for tk in ["AAA", "BBB"]:
            ingest_fundamentals(s, pd.DataFrame({"date": [dt.date(2019, 12, 1)], "ticker": [tk],
                                                 "fcf_yield": [0.05]}), "fmp",
                                availability_lag_days=0)

        result = check_data_quality_gate(s, ["AAA", "BBB"], today)
        assert result.passed, result.failures


def test_gate_fails_on_stale_prices(session_factory):
    with session_factory() as s:
        old = dt.date(2019, 1, 1)
        today = dt.date(2020, 3, 1)
        for tk in ["AAA", "BBB"]:
            ingest_prices(s, pd.DataFrame({"date": [old], "ticker": [tk],
                                           "adj_close": [10.0], "volume": [100]}), "yfinance")
        result = check_data_quality_gate(s, ["AAA", "BBB"], today, max_price_staleness_days=5)
        assert not result.passed
        assert any("stale" in f or "older than" in f for f in result.failures)


def test_gate_fails_on_missing_macro_series(session_factory):
    with session_factory() as s:
        today = dt.date(2020, 3, 1)
        ingest_prices(s, pd.DataFrame({"date": [today], "ticker": ["AAA"],
                                       "adj_close": [10.0], "volume": [100]}), "yfinance")
        result = check_data_quality_gate(s, ["AAA"], today, min_price_coverage=0.1)
        assert not result.passed
        assert any("no observations" in f for f in result.failures)


def test_gate_fails_on_insufficient_fundamentals_coverage(session_factory):
    with session_factory() as s:
        today = dt.date(2020, 3, 1)
        for tk in ["AAA", "BBB", "CCC", "DDD"]:
            ingest_prices(s, pd.DataFrame({"date": [today], "ticker": [tk],
                                           "adj_close": [10.0], "volume": [100]}), "yfinance")
        for series in ["credit_spread", "rate_10y", "vix", "benchmark_adj_close"]:
            ingest_macro(s, pd.DataFrame({"date": [today], series: [1.0]}), "fred")
        # only 1 of 4 tickers has fundamentals -> 25% coverage
        ingest_fundamentals(s, pd.DataFrame({"date": [today], "ticker": ["AAA"],
                                             "fcf_yield": [0.05]}), "fmp", availability_lag_days=0)

        result = check_data_quality_gate(s, ["AAA", "BBB", "CCC", "DDD"], today,
                                         min_fundamentals_coverage=0.5, min_price_coverage=0.1)
        assert not result.passed
        assert any("fundamentals coverage" in f for f in result.failures)
