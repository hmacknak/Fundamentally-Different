"""Factor payoff persistence diagnostic.

Answers a question this project has never directly tested: does a factor's
realized cross-sectional payoff persist from one rebalance to the next
(which would justify weighting rankings by trailing-average payoff, as
priorities.py currently does), or does it mean-revert (which would make
trailing-average weighting actively harmful -- overweighting exactly what
is statistically due to fade)?

Deliberately tests the RAW per-date payoff series (`ic` from
scoring.score_factors_by_date), not the rolling mean (`rolling_ic`). A
rolling window's overlapping observations are mechanically autocorrelated
regardless of any true persistence in the underlying payoff -- testing the
rolling series would just measure "does my smoothing window smooth,"
not the real question.

Persistence coefficient = OLS beta of ic_t on ic_(t-lag) (an AR(lag)
coefficient), using the same estimator (stats_utils.ols_with_tstats)
already used throughout scoring.py/interactions.py, for consistency and
auditability. All (factor, lag) pairs are tested jointly and corrected
with Benjamini-Hochberg FDR, matching the discipline already applied to
factor x macro interactions -- this is a diagnostic, not license to test
one factor at a time until something looks interesting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats_utils import bh_fdr, ols_with_tstats

MIN_OBS = 8
LAGS = (1, 4)
SIG_T = 1.96


def _classify(beta, significant):
    if beta is None or pd.isna(beta):
        return "inconclusive (insufficient history)"
    if not significant:
        return "inconclusive (not distinguishable from noise)"
    return "persistent (momentum in payoff)" if beta > 0 else "mean-reverting"


def factor_payoff_persistence(factor_scores, lags=LAGS, fdr_threshold=0.10):
    """Per (factor, lag) AR(lag) coefficient of the raw per-date payoff (`ic`).

    Returns a DataFrame: factor, lag, beta, t_stat, p_value, q_value,
    significant_fdr, n, classification. classification is only meaningful
    once significant_fdr is known, so it is finalized after the FDR pass.
    """
    fs = factor_scores.sort_values(["factor", "date"])
    rows = []
    for fac, g in fs.groupby("factor"):
        s = g.set_index("date")["ic"]
        for lag in lags:
            x = s.shift(lag)
            df = pd.DataFrame({"x": x, "y": s}).dropna()
            n = len(df)
            if n < MIN_OBS:
                rows.append({"factor": fac, "lag": lag, "beta": np.nan,
                            "t_stat": np.nan, "p_value": np.nan, "n": n})
                continue
            res = ols_with_tstats(df["x"].values, df["y"].values)
            if res is None:
                rows.append({"factor": fac, "lag": lag, "beta": np.nan,
                            "t_stat": np.nan, "p_value": np.nan, "n": n})
                continue
            rows.append({
                "factor": fac, "lag": lag,
                "beta": float(res["beta"][1]), "t_stat": float(res["t"][1]),
                "p_value": float(res["p"][1]), "n": int(res["n"]),
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["q_value"] = bh_fdr(out["p_value"].values)
    out["significant_fdr"] = out["q_value"] <= fdr_threshold
    out["n_tests_in_family"] = len(out)
    out["classification"] = [
        _classify(r["beta"], r["significant_fdr"]) for _, r in out.iterrows()
    ]
    return out.sort_values(["factor", "lag"]).reset_index(drop=True)
