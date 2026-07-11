import numpy as np
import pandas as pd
import pytest

from amp.features import (
    asof_merge_fundamentals,
    build_macro_states,
    derive_fundamental_factors,
    rank_factors,
)


def test_asof_merge_excludes_fundamentals_inside_the_lag_window():
    panel = pd.DataFrame({"date": [pd.Timestamp("2020-04-01")], "ticker": ["AAA"]})
    fundamentals = pd.DataFrame({
        "date": [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-15"), pd.Timestamp("2020-03-25")],
        "ticker": ["AAA", "AAA", "AAA"],
        "fcf_yield": [0.01, 0.02, 0.03],
    })
    # cutoff = 2020-04-01 - 60d = 2020-02-01; only the 2020-01-01 observation qualifies
    merged = asof_merge_fundamentals(panel, fundamentals, lag_days=60)
    assert merged.loc[0, "fcf_yield"] == 0.01
    assert merged.loc[0, "fundamental_date"] == pd.Timestamp("2020-01-01")


def test_asof_merge_uses_latest_available_observation_within_lag():
    panel = pd.DataFrame({"date": [pd.Timestamp("2020-06-01")], "ticker": ["AAA"]})
    fundamentals = pd.DataFrame({
        "date": [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-01"), pd.Timestamp("2020-05-01")],
        "ticker": ["AAA", "AAA", "AAA"],
        "fcf_yield": [0.01, 0.02, 0.03],
    })
    # cutoff = 2020-06-01 - 60d = 2020-04-02; latest qualifying obs is 2020-03-01
    merged = asof_merge_fundamentals(panel, fundamentals, lag_days=60)
    assert merged.loc[0, "fcf_yield"] == 0.02


def test_asof_merge_has_no_fundamental_when_none_qualify():
    panel = pd.DataFrame({"date": [pd.Timestamp("2020-02-01")], "ticker": ["AAA"]})
    fundamentals = pd.DataFrame({
        "date": [pd.Timestamp("2020-01-25")],
        "ticker": ["AAA"],
        "fcf_yield": [0.01],
    })
    # cutoff = 2020-02-01 - 60d = 2019-12-03; no fundamental observation qualifies
    merged = asof_merge_fundamentals(panel, fundamentals, lag_days=60)
    assert pd.isna(merged.loc[0, "fcf_yield"])


def test_build_macro_states_has_no_lookahead():
    dates = pd.date_range("2020-01-01", periods=20, freq="ME")
    macro = pd.DataFrame({"date": dates, "credit_spread": np.linspace(1, 5, 20)})
    full = build_macro_states(macro)
    partial = build_macro_states(macro.iloc[:15])
    pd.testing.assert_frame_equal(
        full.iloc[:15].reset_index(drop=True), partial.reset_index(drop=True)
    )


def test_derive_fundamental_factors_inverts_and_computes_yields():
    f = pd.DataFrame({"debt_to_equity": [1.0], "pe": [10.0], "ev_ebitda": [8.0]})
    out = derive_fundamental_factors(f)
    assert out["debt_to_equity_inv"].iloc[0] == -1.0
    assert out["earnings_yield"].iloc[0] == pytest.approx(0.1)
    assert out["ev_ebitda_inv"].iloc[0] == pytest.approx(0.125)


def test_derive_fundamental_factors_handles_nonpositive_pe_and_ev_ebitda():
    f = pd.DataFrame({"debt_to_equity": [1.0], "pe": [-5.0], "ev_ebitda": [0.0]})
    out = derive_fundamental_factors(f)
    assert np.isnan(out["earnings_yield"].iloc[0])
    assert np.isnan(out["ev_ebitda_inv"].iloc[0])


def test_rank_factors_produces_percentile_ranks_per_date():
    panel = pd.DataFrame({
        "date": ["2020-01-01"] * 4,
        "ticker": ["A", "B", "C", "D"],
        "fcf_yield": [1, 2, 3, 4],
    })
    ranked = rank_factors(panel, ["fcf_yield"])
    assert ranked["fcf_yield_rank"].max() == 1.0
    assert ranked["fcf_yield_rank"].is_monotonic_increasing


def test_rank_factors_sector_neutral_ranks_within_sector_only():
    panel = pd.DataFrame({
        "date": ["2020-01-01"] * 4,
        "sector": ["Tech", "Tech", "Fin", "Fin"],
        "fcf_yield": [1, 2, 10, 20],
    })
    ranked = rank_factors(panel, ["fcf_yield"], sector_neutral=True)
    assert ranked["fcf_yield_rank"].tolist() == [0.5, 1.0, 0.5, 1.0]
