import numpy as np
import pandas as pd

from amp.persistence import factor_payoff_persistence


def _factor_scores(ic_values, factor="fac_a"):
    n = len(ic_values)
    dates = pd.date_range("2015-01-01", periods=n, freq="QE")
    return pd.DataFrame({"date": dates, "factor": [factor] * n, "ic": ic_values,
                         "spread": ic_values, "payoff_slope": ic_values,
                         "n_stocks": [50] * n})


def test_persistent_series_is_classified_as_momentum():
    rng = np.random.default_rng(0)
    n = 40
    ic = np.zeros(n)
    ic[0] = rng.normal()
    for i in range(1, n):
        # strong positive AR(1): today's payoff echoes yesterday's
        ic[i] = 0.85 * ic[i - 1] + rng.normal(scale=0.05)
    out = factor_payoff_persistence(_factor_scores(ic))
    lag1 = out[(out["factor"] == "fac_a") & (out["lag"] == 1)].iloc[0]
    assert lag1["beta"] > 0
    assert lag1["significant_fdr"]
    assert "persistent" in lag1["classification"]


def test_mean_reverting_series_is_classified_as_mean_reverting():
    rng = np.random.default_rng(1)
    n = 40
    ic = np.zeros(n)
    ic[0] = rng.normal()
    for i in range(1, n):
        # strong negative AR(1): payoff flips sign each period
        ic[i] = -0.85 * ic[i - 1] + rng.normal(scale=0.05)
    out = factor_payoff_persistence(_factor_scores(ic))
    lag1 = out[(out["factor"] == "fac_a") & (out["lag"] == 1)].iloc[0]
    assert lag1["beta"] < 0
    assert lag1["significant_fdr"]
    assert lag1["classification"] == "mean-reverting"


def test_pure_noise_is_inconclusive():
    rng = np.random.default_rng(2)
    ic = rng.normal(scale=0.1, size=40)
    out = factor_payoff_persistence(_factor_scores(ic))
    lag1 = out[(out["factor"] == "fac_a") & (out["lag"] == 1)].iloc[0]
    assert not lag1["significant_fdr"]
    assert "inconclusive" in lag1["classification"]


def test_insufficient_history_is_inconclusive_not_crash():
    ic = [0.1, 0.2, -0.1]
    out = factor_payoff_persistence(_factor_scores(ic))
    lag1 = out[(out["factor"] == "fac_a") & (out["lag"] == 1)].iloc[0]
    assert np.isnan(lag1["beta"])
    assert lag1["classification"] == "inconclusive (insufficient history)"


def test_tests_are_fdr_corrected_jointly_across_factors_and_lags():
    rng = np.random.default_rng(3)
    n = 40
    fs = pd.concat([
        _factor_scores(rng.normal(scale=0.1, size=n), factor="noise_a"),
        _factor_scores(rng.normal(scale=0.1, size=n), factor="noise_b"),
    ], ignore_index=True)
    out = factor_payoff_persistence(fs)
    assert out["n_tests_in_family"].iloc[0] == len(out)
    assert set(out["factor"]) == {"noise_a", "noise_b"}
    assert set(out["lag"]) == {1, 4}


def test_empty_input_returns_empty_frame():
    out = factor_payoff_persistence(pd.DataFrame(columns=["date", "factor", "ic"]))
    assert out.empty
