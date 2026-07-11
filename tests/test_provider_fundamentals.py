import pandas as pd
import pytest

from service.providers.fundamentals import (
    compute_revenue_growth_yoy_per_share,
    map_fmp_period_to_fundamentals_row,
)


def test_map_fmp_period_maps_known_fields():
    key_metric = {
        "date": "2020-03-31", "freeCashFlowYield": 0.05, "debtToEquity": 0.8,
        "roe": 0.12, "peRatio": 18.0, "enterpriseValueOverEBITDA": 11.0,
        "dividendYield": 0.02, "revenuePerShare": 10.0,
    }
    ratio = {"interestCoverage": 9.0, "grossProfitMargin": 0.4, "operatingProfitMargin": 0.15}

    row = map_fmp_period_to_fundamentals_row("AAA", key_metric, ratio)

    assert row["ticker"] == "AAA"
    assert row["fcf_yield"] == 0.05
    assert row["debt_to_equity"] == 0.8
    assert row["roe"] == 0.12
    assert row["pe"] == 18.0
    assert row["ev_ebitda"] == 11.0
    assert row["dividend_yield"] == 0.02
    assert row["interest_coverage"] == 9.0
    assert row["gross_margin"] == 0.4
    assert row["operating_margin"] == 0.15


def test_map_fmp_period_never_fabricates_unavailable_fields():
    row = map_fmp_period_to_fundamentals_row("AAA", {"date": "2020-03-31"}, {})
    assert row["free_cash_flow_margin"] is None
    assert row["eps_revision"] is None
    assert row["shares_dilution"] is None


def test_map_fmp_period_missing_ratio_fields_are_none():
    row = map_fmp_period_to_fundamentals_row("AAA", {"date": "2020-03-31"}, {})
    assert row["interest_coverage"] is None
    assert row["gross_margin"] is None


def test_compute_revenue_growth_yoy_per_share():
    rows = []
    for i, rps in enumerate([10.0, 10.5, 11.0, 11.5, 12.0]):
        rows.append({"ticker": "AAA", "date": pd.Timestamp("2020-01-01") + pd.DateOffset(months=3 * i),
                     "_revenue_per_share": rps})
    df = pd.DataFrame(rows)

    out = compute_revenue_growth_yoy_per_share(df)

    assert "_revenue_per_share" not in out.columns
    last = out.iloc[-1]
    assert last["revenue_growth"] == pytest.approx(12.0 / 10.0 - 1.0)
