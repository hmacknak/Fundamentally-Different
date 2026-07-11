"""Walk-forward out-of-sample evaluation of the priority-weighted ranking.

Per docs/QUANT_METHODOLOGY.md's "Required additions" (walk-forward
out-of-sample evaluation): tests whether ranking stocks by the inferred
market priorities at each historical rebalance date -- using only
information available as of that date -- would have produced positive
forward excess returns. This evaluates the composite RANKING STRATEGY,
downstream of the per-factor IC diagnostics scoring.py already covers.

No new point-in-time machinery is needed here: rolling_ic (scoring.py) is
already computed with a trailing-only pandas `.rolling()` window, so a
priority score at date t already reflects only information through t.
Re-running composite_stock_ranks at each historical date (instead of only
the latest one) is therefore already leakage-free.

Sample-size honesty is the whole point of this module: real rebalance
history is short, so treat every summary stat here as exploratory rather
than a validated backtest, and say so plainly in any output.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import priorities


def walk_forward_evaluate(panel, priority_scores, factors_present, top_n=20,
                          weight_smoothing_periods=priorities.WEIGHT_SMOOTHING_PERIODS):
    """For each historical rebalance date with usable priority scores, rank
    stocks using ONLY that date's priority scores, then look up the realized
    forward excess return of the resulting top-N portfolio.

    Returns a DataFrame: date, n_holdings, portfolio_forward_excess_return, hit.
    """
    dates = sorted(priority_scores["date"].unique())
    rows = []
    for dt in dates:
        ranks, _weights, _ranked_date = priorities.composite_stock_ranks(
            panel, priority_scores, factors_present, top_n=top_n, as_of_date=dt,
            weight_smoothing_periods=weight_smoothing_periods)
        if ranks.empty:
            continue
        fwd = panel[panel["date"] == dt].set_index("ticker")["forward_excess_return"]
        realized = ranks.set_index("ticker")["composite_score"].to_frame().join(fwd, how="left")
        valid = realized["forward_excess_return"].dropna()
        if valid.empty:
            continue
        rows.append({
            "date": dt,
            "n_holdings": int(len(valid)),
            "portfolio_forward_excess_return": float(valid.mean()),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out["hit"] = out["portfolio_forward_excess_return"] > 0
    return out


SMALL_SAMPLE_THRESHOLD = 20

# Cap each tail at this quantile before computing the winsorized headline
# stats below. 2026-07-11 (see docs/DECISIONS.md): added after real walk-forward
# data showed 2 of 38 quarters -- both large momentum-driven moves -- accounted
# for most of the headline mean return. Winsorizing bounds any single
# quarter's influence without discarding it, and is reported ALONGSIDE the raw
# stats (never in place of them) so the outlier sensitivity stays visible
# rather than silently smoothed away.
WINSORIZE_LIMIT = 0.05


def _winsorized_mean_se_t(values):
    n = len(values)
    if n < 4:
        # too few points for percentile capping to mean anything distinct
        # from the raw mean -- skip capping rather than clip on a coin flip
        capped = values
    else:
        lo, hi = np.quantile(values, [WINSORIZE_LIMIT, 1 - WINSORIZE_LIMIT])
        capped = values.clip(lower=lo, upper=hi)
    mean = float(capped.mean())
    se = float(capped.std(ddof=1) / np.sqrt(n)) if n > 1 else np.nan
    t_stat = mean / se if se and se > 0 else np.nan
    return mean, se, t_stat


def summarize_walk_forward(wf_results):
    """Headline stats with an explicit small-sample warning -- the number of
    real rebalance periods this project has seen is the actual constraint on
    how much to trust these numbers, not anything about the code.

    Reports both the raw stats and a winsorized variant (see WINSORIZE_LIMIT)
    side by side -- winsorizing is a robustness check on outlier sensitivity,
    not a replacement for the raw number, so both are always returned.
    """
    if wf_results.empty:
        return {
            "n_periods": 0,
            "mean_forward_excess_return": np.nan,
            "se": np.nan,
            "t_stat": np.nan,
            "hit_rate": np.nan,
            "mean_forward_excess_return_winsorized": np.nan,
            "se_winsorized": np.nan,
            "t_stat_winsorized": np.nan,
            "winsorize_limit": WINSORIZE_LIMIT,
            "warning": "No rebalance periods had enough trailing history to evaluate.",
        }
    n = len(wf_results)
    returns = wf_results["portfolio_forward_excess_return"]
    mean_ret = float(returns.mean())
    se = float(returns.std(ddof=1) / np.sqrt(n)) if n > 1 else np.nan
    t_stat = mean_ret / se if se and se > 0 else np.nan
    hit_rate = float(wf_results["hit"].mean())
    w_mean, w_se, w_t = _winsorized_mean_se_t(returns)
    warning = (
        f"Only {n} real historical rebalance period(s) available -- treat this as "
        f"exploratory, not a validated backtest, until more real history accumulates."
        if n < SMALL_SAMPLE_THRESHOLD else None
    )
    return {
        "n_periods": n,
        "mean_forward_excess_return": mean_ret,
        "se": se,
        "t_stat": t_stat,
        "hit_rate": hit_rate,
        "mean_forward_excess_return_winsorized": w_mean,
        "se_winsorized": w_se,
        "t_stat_winsorized": w_t,
        "winsorize_limit": WINSORIZE_LIMIT,
        "warning": warning,
    }
