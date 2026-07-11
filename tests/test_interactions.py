import numpy as np
import pandas as pd

from amp.interactions import run_interaction_tests


def test_run_interaction_tests_detects_a_planted_relationship():
    dates = pd.date_range("2020-01-01", periods=30, freq="QE")
    rng = np.random.default_rng(0)
    macro = rng.normal(size=30)
    slope = 0.5 * macro + rng.normal(scale=0.05, size=30)
    factor_scores = pd.DataFrame({"date": dates, "factor": "fcf_yield", "payoff_slope": slope})
    panel = pd.DataFrame({"date": dates, "credit_spread_z": macro}).drop_duplicates("date")
    out = run_interaction_tests(factor_scores, panel, ["credit_spread_z"],
                                 min_obs=12, fdr_threshold=0.10)
    row = out.iloc[0]
    assert row["interaction_beta"] > 0
    assert bool(row["significant_fdr"])


def test_run_interaction_tests_skips_pairs_below_min_obs():
    dates = pd.date_range("2020-01-01", periods=5, freq="QE")
    factor_scores = pd.DataFrame({"date": dates, "factor": "fcf_yield",
                                  "payoff_slope": [0.1, 0.2, 0.1, 0.15, 0.12]})
    panel = pd.DataFrame({"date": dates, "credit_spread_z": [0.1, 0.2, 0.3, 0.4, 0.5]})
    out = run_interaction_tests(factor_scores, panel, ["credit_spread_z"], min_obs=12)
    assert out.empty


def test_run_interaction_tests_applies_bh_fdr_correction():
    dates = pd.date_range("2020-01-01", periods=30, freq="QE")
    rng = np.random.default_rng(1)
    # pure noise across many factor x macro pairs: expect few/no FDR survivors
    frames = []
    for fac in ["f1", "f2", "f3", "f4", "f5"]:
        frames.append(pd.DataFrame({
            "date": dates, "factor": fac,
            "payoff_slope": rng.normal(size=30),
        }))
    factor_scores = pd.concat(frames, ignore_index=True)
    panel = pd.DataFrame({
        "date": dates,
        "m1": rng.normal(size=30), "m2": rng.normal(size=30), "m3": rng.normal(size=30),
    })
    out = run_interaction_tests(factor_scores, panel, ["m1", "m2", "m3"], min_obs=12)
    assert "q_value" in out.columns
    assert int(out["significant_fdr"].sum()) <= 2  # noise: expect ~0 survivors at q<=0.10
