"""Plain-English report — explanation layer, strictly downstream of calculation.

Language rules enforced here:
- Only FDR-surviving interactions get narrated.
- Every claim carries its statistic (score, t, q, n).
- Hedged verbs only: 'appears', 'is consistent with', 'evidence suggests'.
"""
import pandas as pd

MECHANISM_HINTS = {
    ("fcf_yield", "credit_spread_z"):
        "consistent with the market rewarding internally funded businesses when external capital is expensive",
    ("debt_to_equity_inv", "credit_spread_z"):
        "consistent with a rising penalty on refinancing risk when credit conditions tighten",
    ("interest_coverage", "credit_spread_z"):
        "consistent with debt-service capacity mattering more under credit stress",
    ("earnings_yield", "rate_10y_z"):
        "consistent with valuation discipline mattering more when discount rates are high",
    ("dividend_yield", "rate_10y_z"):
        "consistent with yield competition from bonds affecting the payoff to dividend payers",
    ("momentum_6m", "bench_trend_6m"):
        "consistent with momentum being a trending-market phenomenon",
    ("revenue_growth", "rate_10y_chg_3m"):
        "consistent with long-duration growth repricing when rates move",
    ("commodity_sensitivity", "cpi_yoy_z"):
        "consistent with commodity-linked revenues acting as an inflation hedge",
}


def _arrow(x, up=0.01, down=-0.01):
    if pd.isna(x):
        return "n/a"
    return "strengthening" if x > up else ("weakening" if x < down else "stable")


def _fmt(x, nd=3):
    return "n/a" if pd.isna(x) else f"{x:.{nd}f}"


def build_report(priority_scores, rolled, interactions, ranks, weights, overlap,
                 latest_date, audit, config, synth_validation=None,
                 walk_forward_summary=None):
    L = []
    L.append("# Market Priority Report")
    L.append(f"\nAs of rebalance date: **{pd.Timestamp(latest_date).date()}**")
    L.append(f"Universe: {audit['ticker_counts']['overlap']} tickers | "
             f"Rebalance: {config['rebalance']} | Holding: {config['holding_months']}m | "
             f"Rolling window: {config['rolling_windows']} periods | "
             f"Fundamental reporting lag enforced: {config['fundamental_lag_days']} days")
    L.append("\nReturns are benchmark-relative (excess) throughout.\n")

    # ---- current priorities ----
    L.append("## What the market appears to be prioritizing")
    latest = priority_scores[priority_scores["date"] == priority_scores["date"].max()]
    latest = latest.sort_values("priority_score", ascending=False)
    L.append("\n| Priority | Score (mean rolling IC) | Q-spread | Trend | Evidence base |")
    L.append("|---|---|---|---|---|")
    for _, r in latest.iterrows():
        L.append(f"| {r['priority']} | {_fmt(r['priority_score'])} | "
                 f"{_fmt(r['priority_spread'], 4)} | {_arrow(r['strengthening'])} | "
                 f"{int(r['n_members_scored'])}/{int(r['n_members_defined'])} factors |")
    top = latest.iloc[0]
    second = latest.iloc[1] if len(latest) > 1 else None
    L.append(f"\nThe strongest current evidence points to **{top['priority']}** "
             f"(score {_fmt(top['priority_score'])}, {_arrow(top['strengthening'])})"
             + (f", followed by **{second['priority']}** ({_fmt(second['priority_score'])})."
                if second is not None else "."))
    L.append("\nScores are rolling averages over a small number of quarterly observations; "
             "treat rankings between closely scored priorities as indistinguishable.")

    # ---- factor evidence ----
    L.append("\n## Factor evidence behind the diagnosis")
    last_f = rolled[rolled["date"] == rolled["date"].max()].sort_values("rolling_ic", ascending=False)
    L.append("\n| Factor | Rolling IC | ±SE | t | Hit rate | Trend (4-period) |")
    L.append("|---|---|---|---|---|---|")
    for _, r in last_f.iterrows():
        L.append(f"| {r['factor']} | {_fmt(r['rolling_ic'])} | {_fmt(r['rolling_ic_se'])} | "
                 f"{_fmt(r['rolling_ic_t'], 2)} | {_fmt(r['hit_rate'], 2)} | "
                 f"{_arrow(r['strengthening_4p'])} |")

    # ---- interactions / the why ----
    L.append("\n## Why these criteria may matter now (interaction evidence)")
    if interactions is None or interactions.empty:
        L.append("\nNo interaction tests could be run (insufficient history).")
    else:
        surv = interactions[interactions["significant_fdr"]]
        n_tests = int(interactions["n_tests_in_family"].iloc[0])
        L.append(f"\n{n_tests} factor x macro pairs tested jointly; "
                 f"Benjamini-Hochberg FDR at q<=0.10 controls false discoveries. "
                 f"**{len(surv)} relationship(s) survive.** Non-survivors are not narrated.")
        if len(surv):
            L.append("\n| Factor | Macro state | b | t | q | n | Reading |")
            L.append("|---|---|---|---|---|---|---|")
            for _, r in surv.iterrows():
                direction = "higher" if r["interaction_beta"] > 0 else "lower"
                hint = MECHANISM_HINTS.get((r["factor"], r["macro_state"]),
                                           "mechanism not pre-mapped — interpret with care")
                L.append(f"| {r['factor']} | {r['macro_state']} | "
                         f"{_fmt(r['interaction_beta'], 4)} | {_fmt(r['t_stat'], 2)} | "
                         f"{_fmt(r['q_value'], 3)} | {int(r['n_periods'])} | "
                         f"payoff tends {direction} when this state is elevated — {hint} |")
            L.append("\nThese are conditional associations, not causal proof.")

    # ---- shared evidence ----
    L.append("\n## Shared evidence between priorities (read before comparing them)")
    L.append("\nPriorities share member factors by design, so their scores are correlated. "
             "Jaccard overlap of evidence sets:")
    L.append("\n| | " + " | ".join(overlap.columns) + " |")
    L.append("|---" * (len(overlap.columns) + 1) + "|")
    for idx, row in overlap.iterrows():
        L.append(f"| **{idx}** | " + " | ".join(_fmt(v, 2) for v in row.values) + " |")

    # ---- ranks ----
    L.append("\n## Top-ranked candidates under the current priority weights")
    L.append("\nRanking is downstream of the diagnosis. Weights (positive-score normalized, "
             "averaged over the trailing quarters to avoid one hot quarter dominating): "
             + ", ".join(f"{k} {v:.0%}" for k, v in weights.items() if v > 0.001))
    L.append("\n| # | Ticker | Composite |")
    L.append("|---|---|---|")
    for _, r in ranks.iterrows():
        L.append(f"| {int(r['rank'])} | {r['ticker']} | {_fmt(r['composite_score'])} |")

    # ---- walk-forward (exploratory) ----
    if walk_forward_summary is not None and walk_forward_summary["n_periods"] > 0:
        wf = walk_forward_summary
        L.append("\n## Walk-forward check: would this ranking have worked historically? (exploratory)")
        L.append(f"\nAt each of {wf['n_periods']} historical rebalance date(s), ranked stocks "
                 f"using only priority scores available as of that date, then measured the "
                 f"realized forward excess return of the resulting top-N portfolio.")
        L.append("\n| | Mean forward excess return | ±SE | t | Hit rate |")
        L.append("|---|---|---|---|---|")
        L.append(f"| Raw ({wf['n_periods']} periods) | {_fmt(wf['mean_forward_excess_return'], 4)} | "
                 f"{_fmt(wf['se'], 4)} | {_fmt(wf['t_stat'], 2)} | {_fmt(wf['hit_rate'], 2)} |")
        if "mean_forward_excess_return_winsorized" in wf:
            limit_pct = wf.get("winsorize_limit", 0.05) * 100
            L.append(f"| Winsorized (±{limit_pct:.0f}%ile capped) | "
                     f"{_fmt(wf['mean_forward_excess_return_winsorized'], 4)} | "
                     f"{_fmt(wf['se_winsorized'], 4)} | {_fmt(wf['t_stat_winsorized'], 2)} | n/a |")
            L.append("\nThe winsorized row caps the most extreme per-period returns at the "
                     f"{limit_pct:.0f}th/{100 - limit_pct:.0f}th percentile before averaging, so "
                     "a couple of outsized quarters can't single-handedly set the headline "
                     "number. It's a robustness check, not a replacement for the raw row above "
                     "-- a large gap between the two rows means the raw result is being driven "
                     "by a small number of periods and should be read with extra caution.")
        if wf["warning"]:
            L.append(f"\n**{wf['warning']}**")

    # ---- synthetic validation ----
    if synth_validation:
        L.append("\n## Control test: planted-signal recovery (synthetic run)")
        for line in synth_validation:
            L.append(f"- {line}")

    L.append("\n## Limitations (auto-included)")
    L.append("- Research tool, not investment advice. No trading, no performance guarantee.")
    L.append("- Quarterly rebalancing yields few observations; all statistics carry wide uncertainty.")
    L.append("- Correlation-based evidence throughout; interaction terms support, never prove, mechanisms.")
    L.append("- Real-world use requires point-in-time fundamentals, survivorship-free universe, "
             "transaction costs, and out-of-sample validation.")
    if walk_forward_summary is not None and walk_forward_summary["n_periods"] > 0:
        L.append("- Walk-forward results above use overlapping holding periods and no transaction "
                 "costs; treat as a directional check, not a strategy return estimate.")
    return "\n".join(L) + "\n"
