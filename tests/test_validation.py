import pandas as pd
import pytest

from amp.validation import DataValidationError, validate_inputs

FUND_COLS = {
    "date": ["2020-01-01"], "ticker": ["A"], "fcf_yield": [0.1], "debt_to_equity": [1],
    "roe": [0.1], "revenue_growth": [0.1], "pe": [10], "ev_ebitda": [8],
    "dividend_yield": [0.01],
}


def test_validate_inputs_raises_on_missing_file(tmp_path):
    with pytest.raises(DataValidationError):
        validate_inputs(str(tmp_path / "missing.csv"), str(tmp_path / "missing2.csv"),
                        str(tmp_path / "missing3.csv"), str(tmp_path))


def test_validate_inputs_raises_on_missing_required_columns(tmp_path):
    p = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2020-01-01"]}).to_csv(p, index=False)  # missing ticker/adj_close/volume
    f = tmp_path / "fundamentals.csv"
    pd.DataFrame(FUND_COLS).to_csv(f, index=False)
    m = tmp_path / "macro.csv"
    pd.DataFrame({"date": ["2020-01-01"]}).to_csv(m, index=False)
    with pytest.raises(DataValidationError):
        validate_inputs(str(p), str(f), str(m), str(tmp_path))


def test_validate_inputs_deduplicates_and_reports_issues(tmp_path):
    p = tmp_path / "prices.csv"
    pd.DataFrame({
        "date": ["2020-01-01", "2020-01-01", "2020-01-02"],
        "ticker": ["A", "A", "A"],
        "adj_close": [10, 11, 12],
        "volume": [100, 100, 100],
    }).to_csv(p, index=False)
    f = tmp_path / "fundamentals.csv"
    pd.DataFrame(FUND_COLS).to_csv(f, index=False)
    m = tmp_path / "macro.csv"
    pd.DataFrame({"date": ["2020-01-01"]}).to_csv(m, index=False)

    prices, fundamentals, macro, audit = validate_inputs(str(p), str(f), str(m), str(tmp_path))
    assert len(prices) == 2  # duplicate (date, ticker) row dropped, keeping last
    assert any("duplicate" in issue for issue in audit["issues"])
    assert audit["ticker_counts"]["overlap"] == 1


def test_validate_inputs_drops_nonpositive_prices(tmp_path):
    p = tmp_path / "prices.csv"
    pd.DataFrame({
        "date": ["2020-01-01", "2020-01-02"],
        "ticker": ["A", "A"],
        "adj_close": [10, -5],
        "volume": [100, 100],
    }).to_csv(p, index=False)
    f = tmp_path / "fundamentals.csv"
    pd.DataFrame(FUND_COLS).to_csv(f, index=False)
    m = tmp_path / "macro.csv"
    pd.DataFrame({"date": ["2020-01-01"]}).to_csv(m, index=False)

    prices, fundamentals, macro, audit = validate_inputs(str(p), str(f), str(m), str(tmp_path))
    assert len(prices) == 1
    assert (prices["adj_close"] > 0).all()


def test_validate_inputs_writes_data_quality_report(tmp_path):
    p = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2020-01-01"], "ticker": ["A"], "adj_close": [10], "volume": [100]}
                 ).to_csv(p, index=False)
    f = tmp_path / "fundamentals.csv"
    pd.DataFrame(FUND_COLS).to_csv(f, index=False)
    m = tmp_path / "macro.csv"
    pd.DataFrame({"date": ["2020-01-01"]}).to_csv(m, index=False)

    validate_inputs(str(p), str(f), str(m), str(tmp_path))
    assert (tmp_path / "data_quality_report.md").exists()
