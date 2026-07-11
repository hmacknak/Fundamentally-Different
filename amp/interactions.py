"""Factor x macro interaction testing — the 'why' layer's evidence base.

Design note (replaces the pooled-Ridge spec): a macro variable is constant across
all stocks on a given date, so a cross-sectional factor-x-macro term is not
identified within a date. The honest two-stage estimate:

  Stage 1: per rebalance date, cross-sectional payoff slope of the factor
           (excess forward return per 1sd of factor rank). Computed in scoring.py.
  Stage 2: time-series regression  payoff_slope_t = a + b * macro_state_t.
           b > 0  =>  the factor's payoff tends to be higher when the macro
           state is elevated. That is evidence FOR a conditional story, not
           proof of causation.

All (factor, macro) pairs are tested jointly and corrected with
Benjamini-Hochberg FDR. The narrative layer may only speak about survivors.
"""
import pandas as pd

from .stats_utils import bh_fdr, ols_with_tstats


def run_interaction_tests(factor_scores, panel, macro_cols, min_obs=12, fdr_threshold=0.10):
    """Stage 2 over the full available history of rebalance dates."""
    macro_by_date = (panel[["date"] + [c for c in macro_cols if c in panel.columns]]
                     .drop_duplicates("date").set_index("date").sort_index())
    slopes = factor_scores.pivot(index="date", columns="factor", values="payoff_slope")

    rows = []
    for fac in slopes.columns:
        s = slopes[fac]
        for mc in macro_by_date.columns:
            m = macro_by_date[mc].reindex(s.index)
            df = pd.DataFrame({"slope": s, "macro": m}).dropna()
            if len(df) < min_obs:
                continue
            res = ols_with_tstats(df["macro"].values, df["slope"].values)
            if res is None:
                continue
            rows.append({
                "factor": fac, "macro_state": mc,
                "interaction_beta": float(res["beta"][1]),
                "t_stat": float(res["t"][1]),
                "p_value": float(res["p"][1]),
                "n_periods": int(res["n"]),
                "base_payoff": float(res["beta"][0]),
            })
    it = pd.DataFrame(rows)
    if it.empty:
        return it
    it["q_value"] = bh_fdr(it["p_value"].values)
    it["significant_fdr"] = it["q_value"] <= fdr_threshold
    it["n_tests_in_family"] = len(it)
    return it.sort_values("q_value").reset_index(drop=True)
