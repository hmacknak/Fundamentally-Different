"""Factor sensitivity testing.

Per rebalance date, per factor:
- Spearman rank IC vs forward EXCESS return (benchmark-relative)
- Top-minus-bottom quintile excess return spread
- Per-date cross-sectional payoff slope (for interaction testing downstream)

Rolling layer adds mean, standard error, t-stat, hit rate, and strengthening delta.
Every headline number ships with its uncertainty.
"""
import numpy as np
import pandas as pd

from .stats_utils import ols_with_tstats, quintile_spread, spearman_ic


def score_factors_by_date(panel, factors, return_col="forward_excess_return"):
    rows = []
    for dt, g in panel.groupby("date"):
        y = g[return_col]
        for fac in factors:
            col = fac + "_rank"
            ic, n = spearman_ic(g[col], y)
            spread = quintile_spread(g[col], y)
            # per-date payoff slope on standardized rank (units: excess return per 1sd)
            slope = np.nan
            r = g[col]
            if r.notna().sum() >= 10 and r.std() > 0:
                z = (r - r.mean()) / r.std()
                res = ols_with_tstats(z.values, y.values)
                if res is not None:
                    slope = float(res["beta"][1])
            rows.append({"date": dt, "factor": fac, "ic": ic, "spread": spread,
                         "payoff_slope": slope, "n_stocks": n})
    return pd.DataFrame(rows)


def add_rolling_stats(factor_scores, window):
    fs = factor_scores.sort_values(["factor", "date"]).copy()
    g = fs.groupby("factor")
    fs["rolling_ic"] = g["ic"].transform(lambda s: s.rolling(window, min_periods=max(3, window // 2)).mean())
    fs["rolling_ic_se"] = g["ic"].transform(
        lambda s: s.rolling(window, min_periods=max(3, window // 2)).std()
        / np.sqrt(s.rolling(window, min_periods=max(3, window // 2)).count()))
    fs["rolling_ic_t"] = fs["rolling_ic"] / fs["rolling_ic_se"]
    fs["rolling_spread"] = g["spread"].transform(lambda s: s.rolling(window, min_periods=max(3, window // 2)).mean())
    fs["hit_rate"] = g["ic"].transform(
        lambda s: (s > 0).rolling(window, min_periods=max(3, window // 2)).mean())
    # strengthening: short-run delta and year-over-year delta of the rolling mean
    fs["strengthening_1p"] = g["rolling_ic"].transform(lambda s: s.diff(1))
    fs["strengthening_4p"] = g["rolling_ic"].transform(lambda s: s.diff(4))
    return fs
