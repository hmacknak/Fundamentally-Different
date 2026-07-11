import numpy as np
import pandas as pd
import pytest

from amp.priorities import composite_stock_ranks
from amp.walkforward import summarize_walk_forward, walk_forward_evaluate


def _toy_panel_and_scores():
    dates = pd.to_datetime(["2020-01-01", "2020-04-01", "2020-07-01"])
    panel = pd.DataFrame({
        "date": np.repeat(dates, 2),
        "ticker": ["A", "B"] * 3,
        "fcf_yield_rank": [0.9, 0.1, 0.8, 0.2, 0.7, 0.3],
        "forward_excess_return": [0.05, -0.02, 0.04, -0.01, 0.03, -0.03],
    })
    pscores = pd.DataFrame({
        "date": dates,
        "priority": ["Cash generation"] * 3,
        "priority_score": [0.1, 0.1, 0.1],
    })
    return panel, pscores


def test_walk_forward_evaluate_computes_realized_return_per_date():
    panel, pscores = _toy_panel_and_scores()
    out = walk_forward_evaluate(panel, pscores, ["fcf_yield"], top_n=1)
    assert len(out) == 3
    # top_n=1 -> only ticker A (higher fcf_yield_rank each period) is held
    assert out["portfolio_forward_excess_return"].tolist() == pytest.approx([0.05, 0.04, 0.03])
    assert out["hit"].all()


def test_walk_forward_evaluate_uses_only_trailing_information():
    panel, pscores = _toy_panel_and_scores()
    full = walk_forward_evaluate(panel, pscores, ["fcf_yield"], top_n=1)

    cutoff = pscores["date"].iloc[1]
    truncated_pscores = pscores[pscores["date"] <= cutoff]
    truncated_panel = panel[panel["date"] <= cutoff]
    partial = walk_forward_evaluate(truncated_panel, truncated_pscores, ["fcf_yield"], top_n=1)

    # results for the two shared dates must be identical whether or not future
    # rows exist in the input -- the no-lookahead property this module exists to prove
    pd.testing.assert_frame_equal(
        full.iloc[:2].reset_index(drop=True), partial.reset_index(drop=True)
    )


def test_composite_stock_ranks_as_of_date_matches_historical_slice():
    panel, pscores = _toy_panel_and_scores()
    early_date = pscores["date"].iloc[0]
    ranks_from_full, _, _ = composite_stock_ranks(
        panel, pscores, ["fcf_yield"], as_of_date=early_date)
    ranks_from_truncated, _, _ = composite_stock_ranks(
        panel[panel["date"] == early_date], pscores[pscores["date"] == early_date],
        ["fcf_yield"], as_of_date=early_date,
    )
    pd.testing.assert_frame_equal(
        ranks_from_full.reset_index(drop=True), ranks_from_truncated.reset_index(drop=True)
    )


def test_composite_stock_ranks_explicit_missing_date_returns_empty_not_fallback():
    panel, pscores = _toy_panel_and_scores()
    missing_date = pd.Timestamp("2019-01-01")
    ranks, weights, returned_date = composite_stock_ranks(
        panel, pscores, ["fcf_yield"], as_of_date=missing_date)
    assert ranks.empty
    assert returned_date == missing_date


def test_summarize_walk_forward_flags_small_sample():
    wf = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2020-04-01"]),
        "n_holdings": [1, 1],
        "portfolio_forward_excess_return": [0.05, 0.03],
        "hit": [True, True],
    })
    summary = summarize_walk_forward(wf)
    assert summary["n_periods"] == 2
    assert summary["hit_rate"] == 1.0
    assert summary["warning"] is not None
    assert "exploratory" in summary["warning"]


def test_summarize_walk_forward_large_sample_has_no_warning():
    n = 25
    wf = pd.DataFrame({
        "date": pd.date_range("2010-01-01", periods=n, freq="QE"),
        "n_holdings": [1] * n,
        "portfolio_forward_excess_return": [0.01] * n,
        "hit": [True] * n,
    })
    summary = summarize_walk_forward(wf)
    assert summary["warning"] is None


def test_summarize_walk_forward_empty_input():
    summary = summarize_walk_forward(pd.DataFrame())
    assert summary["n_periods"] == 0
    assert np.isnan(summary["mean_forward_excess_return"])
