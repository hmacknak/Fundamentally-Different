import pytest
import pandas as pd

from amp.priorities import composite_stock_ranks, overlap_matrix, score_priorities


def test_score_priorities_averages_present_member_factors():
    rolled = pd.DataFrame({
        "date": ["2020-01-01"] * 2,
        "factor": ["fcf_yield", "free_cash_flow_margin"],
        "rolling_ic": [0.1, 0.3],
        "rolling_spread": [0.01, 0.02],
        "strengthening_4p": [0.0, 0.0],
    })
    out = score_priorities(rolled, ["fcf_yield", "free_cash_flow_margin"])
    cash_gen = out[out["priority"] == "Cash generation"].iloc[0]
    assert cash_gen["priority_score"] == pytest.approx(0.2)
    assert cash_gen["n_members_scored"] == 2
    assert cash_gen["n_members_defined"] == 3  # operating_margin absent from factors_present


def test_score_priorities_skips_priority_with_no_evidence():
    rolled = pd.DataFrame({
        "date": ["2020-01-01"],
        "factor": ["momentum_6m"],
        "rolling_ic": [0.1],
        "rolling_spread": [0.01],
        "strengthening_4p": [0.0],
    })
    out = score_priorities(rolled, ["momentum_6m"])
    assert "Valuation discipline" not in set(out["priority"])


def test_overlap_matrix_self_overlap_is_one():
    ov = overlap_matrix(["fcf_yield"])
    assert ov.loc["Cash generation", "Cash generation"] == 1.0


def test_overlap_matrix_disjoint_priorities_have_zero_overlap():
    # only revenue_growth present: shared by Growth scarcity only
    ov = overlap_matrix(["revenue_growth"])
    assert ov.loc["Growth scarcity", "Risk avoidance"] == 0.0


def test_composite_stock_ranks_orders_by_score_descending():
    panel = pd.DataFrame({
        "date": ["2020-01-01"] * 2,
        "ticker": ["A", "B"],
        "fcf_yield_rank": [0.9, 0.1],
    })
    pscores = pd.DataFrame({"date": ["2020-01-01"], "priority": ["Cash generation"],
                            "priority_score": [0.5]})
    ranks, weights, latest_date = composite_stock_ranks(panel, pscores, ["fcf_yield"], top_n=2)
    assert ranks.iloc[0]["ticker"] == "A"
    assert ranks.iloc[0]["rank"] == 1
