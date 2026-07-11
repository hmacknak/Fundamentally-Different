#!/usr/bin/env python3
"""Adaptive Market Priority Engine.

Diagnoses what the market appears to be optimizing for, which company criteria
satisfy it, whether those criteria are being rewarded in forward excess returns,
and whether the relationship is strengthening or weakening. Stock ranking is
strictly downstream of the diagnosis.

Run (real data):
  python adaptive_market_priority_engine.py --prices prices.csv \
      --fundamentals fundamentals.csv --macro macro.csv --output output

Run (control test on synthetic data with planted signals):
  python adaptive_market_priority_engine.py --synthetic --output output
"""
import argparse
import json
import os
import platform
import sys
import time

import numpy as np
import pandas as pd

from amp import (
    features, interactions, persistence, priorities, report, scoring, synth,
    validation, walkforward,
)


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices")
    ap.add_argument("--fundamentals")
    ap.add_argument("--macro")
    ap.add_argument("--output", default="output")
    ap.add_argument("--rebalance", default="Q", choices=["Q", "M"])
    ap.add_argument("--holding-months", type=int, default=3)
    ap.add_argument("--rolling-windows", type=int, default=8)
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument("--weight-smoothing-periods", type=int,
                    default=priorities.WEIGHT_SMOOTHING_PERIODS,
                    help="Trailing rebalance periods averaged into each priority's ranking "
                         "weight, instead of only the latest snapshot (damps single-quarter "
                         "spikes, e.g. a momentum surge, from dominating portfolio weight)")
    ap.add_argument("--fundamental-lag-days", type=int, default=60,
                    help="Reporting lag: rebalance at t only sees fundamentals dated <= t - lag")
    ap.add_argument("--sector-neutral", action="store_true",
                    help="Rank factors within sector (requires sector column)")
    ap.add_argument("--fdr", type=float, default=0.10)
    ap.add_argument("--synthetic", action="store_true",
                    help="Generate synthetic data with planted signals and run the control test")
    ap.add_argument("--synthetic-null", action="store_true",
                    help="Control test specificity: synthetic data with ZERO planted effects")
    ap.add_argument("--seed", type=int, default=42)
    return ap.parse_args(argv)


def rebalance_dates_from_prices(px, freq, holding_days):
    idx = px.index
    period = idx.to_period("Q" if freq == "Q" else "M")
    last_of_period = pd.Series(idx, index=idx).groupby(period).max()
    dates = []
    for dt in last_of_period.values:
        i = idx.get_indexer([dt])[0]
        if i >= features.TRADING_DAYS_1Y and i + holding_days < len(idx):
            dates.append(pd.Timestamp(dt))
    return dates


def synth_validation_summary(rolled, interactions_df, gt_path, panel=None):
    """Compare recovered evidence against planted ground truth."""
    with open(gt_path) as fh:
        json.load(fh)  # fail loudly if the ground-truth file is missing/corrupt
    lines = []
    last = rolled[rolled["date"] == rolled["date"].max()].set_index("factor")

    # planted 1: fcf_yield x credit_spread_z conditional effect
    hit = interactions_df[(interactions_df["factor"] == "fcf_yield")
                          & (interactions_df["macro_state"] == "credit_spread_z")]
    if len(hit):
        r = hit.iloc[0]
        ok = (r["interaction_beta"] > 0) and bool(r["significant_fdr"])
        lines.append(f"PLANTED conditional effect (fcf_yield x credit_spread_z): "
                     f"{'RECOVERED' if ok else 'NOT RECOVERED'} "
                     f"(b={r['interaction_beta']:.4f}, t={r['t_stat']:.2f}, q={r['q_value']:.3f})")
    else:
        lines.append("PLANTED fcf_yield x credit_spread_z: test not run (insufficient data)")

    # planted 2: revenue_growth steady positive IC
    if "revenue_growth" in last.index:
        r = last.loc["revenue_growth"]
        ok = pd.notna(r["rolling_ic_t"]) and r["rolling_ic"] > 0 and r["rolling_ic_t"] > 1.5
        lines.append(f"PLANTED unconditional effect (revenue_growth): "
                     f"{'RECOVERED' if ok else 'WEAK/NOT RECOVERED'} "
                     f"(rolling IC={r['rolling_ic']:.3f}, t={r['rolling_ic_t']:.2f})")

    # false positive check: FDR survivors that were NOT planted
    planted_pairs = {("fcf_yield", "credit_spread_z")}
    surv = interactions_df[interactions_df["significant_fdr"]]
    fp = []
    for _, r in surv.iterrows():
        if (r["factor"], r["macro_state"]) in planted_pairs or r["factor"] == "revenue_growth":
            continue
        tag = f"{r['factor']} x {r['macro_state']}"
        if panel is not None and f"{r['factor']}_rank" in panel.columns:
            from scipy.stats import spearmanr
            m = panel[["fcf_yield_rank", f"{r['factor']}_rank"]].dropna()
            if len(m) > 50:
                rho = spearmanr(m.iloc[:, 0], m.iloc[:, 1])[0]
                tag += f" (rank-corr with planted fcf_yield: {rho:+.2f})"
        fp.append(tag)
    if fp:
        lines.append(f"FDR survivors not planted — check correlation with planted factors "
                     f"before calling them false positives: {fp}")
    else:
        lines.append("No unplanted interactions survived FDR — false-positive control PASSED.")
    return lines


def main(argv=None):
    t0 = time.time()
    args = parse_args(argv)
    os.makedirs(args.output, exist_ok=True)

    if args.synthetic or args.synthetic_null:
        synth_dir = os.path.join(args.output, "synthetic_inputs")
        p_path, f_path, m_path = synth.generate(synth_dir, seed=args.seed,
                                                null_mode=args.synthetic_null)
        mode = "NULL (zero effects)" if args.synthetic_null else "planted-signal"
        print(f"[synthetic] generated {mode} data in {synth_dir}")
    else:
        if not (args.prices and args.fundamentals and args.macro):
            print("ERROR: provide --prices/--fundamentals/--macro, or use --synthetic",
                  file=sys.stderr)
            return 2
        p_path, f_path, m_path = args.prices, args.fundamentals, args.macro

    # 1. validate
    prices, fundamentals, macro, audit = validation.validate_inputs(
        p_path, f_path, m_path, args.output)
    print(f"[validate] {audit['ticker_counts']['overlap']} usable tickers; "
          f"{len(audit['issues'])} non-critical issues -> data_quality_report.md")

    # 2. panel construction (point-in-time)
    holding_days = args.holding_months * 21
    px = features.build_price_matrix(prices)
    macro_idx = macro.sort_values("date").set_index("date")
    bench = (macro_idx["benchmark_adj_close"].reindex(px.index, method="ffill")
             if "benchmark_adj_close" in macro_idx.columns
             else px.mean(axis=1))
    rdates = rebalance_dates_from_prices(px, args.rebalance, holding_days)
    print(f"[panel] {len(rdates)} rebalance dates "
          f"({rdates[0].date()} .. {rdates[-1].date()})")

    panel = features.compute_price_features(px, bench, rdates, holding_days)
    cs = (features.compute_commodity_sensitivity(px, macro_idx["wti_oil"], rdates)
          if "wti_oil" in macro_idx.columns else None)
    if cs is not None and len(cs):
        panel = panel.merge(cs, on=["date", "ticker"], how="left")

    fundamentals = features.derive_fundamental_factors(fundamentals)
    panel = features.asof_merge_fundamentals(panel, fundamentals, args.fundamental_lag_days)

    macro_states = features.build_macro_states(macro)
    panel = features.attach_macro(panel, macro_states)
    panel = features.rank_factors(panel, features.FACTOR_COLUMNS,
                                  sector_neutral=args.sector_neutral)
    factors = features.available_factors(panel)
    print(f"[panel] {len(factors)} factors with sufficient coverage: {factors}")
    panel.to_csv(os.path.join(args.output, "panel_rebalance_data.csv"), index=False)

    # 3. factor sensitivity
    fscores = scoring.score_factors_by_date(panel, factors)
    rolled = scoring.add_rolling_stats(fscores, args.rolling_windows)
    rolled.to_csv(os.path.join(args.output, "factor_scores.csv"), index=False)

    # 3.5. persistence diagnostic (exploratory): does a factor's raw per-date
    # payoff persist quarter to quarter (justifying trailing-average
    # weighting, as priorities.py currently does) or mean-revert (which would
    # make that weighting actively harmful)? Diagnostic only -- does not
    # change ranking or weighting behavior.
    persist = persistence.factor_payoff_persistence(fscores, fdr_threshold=args.fdr)
    persist.to_csv(os.path.join(args.output, "factor_persistence.csv"), index=False)
    n_persist_sig = int(persist["significant_fdr"].sum()) if len(persist) else 0
    print(f"[persistence] {len(persist)} factor x lag test(s), "
          f"{n_persist_sig} distinguishable from noise after FDR")
    if len(persist):
        for _, r in persist[persist["significant_fdr"]].iterrows():
            print(f"[persistence] {r['factor']} @ lag {r['lag']}: {r['classification']} "
                  f"(beta={r['beta']:.3f}, t={r['t_stat']:.2f}, q={r['q_value']:.3f})")

    # 4. priorities
    pscores = priorities.score_priorities(rolled, factors)
    pscores.to_csv(os.path.join(args.output, "priority_scores.csv"), index=False)
    ov = priorities.overlap_matrix(factors)

    # 5. interactions (the why layer's evidence)
    macro_cols = [c for c in features.MACRO_STATE_COLUMNS if c in panel.columns]
    itests = interactions.run_interaction_tests(rolled, panel, macro_cols,
                                                fdr_threshold=args.fdr)
    itests.to_csv(os.path.join(args.output, "interaction_tests.csv"), index=False)
    n_surv = int(itests["significant_fdr"].sum()) if len(itests) else 0
    print(f"[interactions] {len(itests)} pairs tested, {n_surv} survive FDR q<={args.fdr}")

    # 6. ranks (downstream of diagnosis)
    ranks, weights, latest_date = priorities.composite_stock_ranks(
        panel, pscores, factors, top_n=args.top_n,
        weight_smoothing_periods=args.weight_smoothing_periods)
    ranks.to_csv(os.path.join(args.output, "latest_stock_ranks.csv"), index=False)

    # 6.5. walk-forward: would this ranking approach have worked historically?
    # Exploratory (docs/QUANT_METHODOLOGY.md's Required Additions) -- every
    # number here should be read with the sample-size caveat front and center.
    wf_results = walkforward.walk_forward_evaluate(
        panel, pscores, factors, top_n=args.top_n,
        weight_smoothing_periods=args.weight_smoothing_periods)
    wf_results.to_csv(os.path.join(args.output, "walk_forward_results.csv"), index=False)
    wf_summary = walkforward.summarize_walk_forward(wf_results)
    print(f"[walk-forward] {wf_summary['n_periods']} historical rebalance(s) evaluated, "
          f"mean forward excess return {wf_summary['mean_forward_excess_return']:.4f} "
          f"(winsorized {wf_summary['mean_forward_excess_return_winsorized']:.4f}), "
          f"hit rate {wf_summary['hit_rate']:.2f}"
          if wf_summary["n_periods"] else "[walk-forward] no evaluable historical periods")
    if wf_summary["warning"]:
        print(f"[walk-forward] WARNING: {wf_summary['warning']}")

    # 7. control-test validation on synthetic runs
    synth_val = None
    if args.synthetic_null:
        surv = itests[itests["significant_fdr"]] if len(itests) else itests
        big_ic = rolled[(rolled["date"] == rolled["date"].max())
                        & (rolled["rolling_ic_t"].abs() > 2.5)]
        surv_pairs = [f"{r['factor']} x {r['macro_state']}" for _, r in surv.iterrows()]
        synth_val = [f"NULL RUN: {len(surv)} interaction(s) survived FDR "
                     f"(expected ~0): {surv_pairs}",
                     f"NULL RUN: {len(big_ic)} factor(s) with |rolling IC t| > 2.5 "
                     f"(expected ~0-1 by chance): {list(big_ic['factor'])}",
                     "Specificity " + ("PASSED" if len(surv) == 0 else "REVIEW NEEDED")]
        for line in synth_val:
            print(f"[control-test] {line}")
    elif args.synthetic:
        synth_val = synth_validation_summary(
            rolled, itests, os.path.join(args.output, "synthetic_inputs", "ground_truth.json"),
            panel=panel)
        for line in synth_val:
            print(f"[control-test] {line}")

    # 8. report + audit trail
    config = {"rebalance": args.rebalance, "holding_months": args.holding_months,
              "rolling_windows": args.rolling_windows, "top_n": args.top_n,
              "fundamental_lag_days": args.fundamental_lag_days,
              "weight_smoothing_periods": args.weight_smoothing_periods,
              "sector_neutral": args.sector_neutral, "fdr": args.fdr,
              "synthetic": args.synthetic, "synthetic_null": args.synthetic_null, "seed": args.seed}
    md = report.build_report(pscores, rolled, itests, ranks, weights, ov,
                             latest_date, audit, config, synth_validation=synth_val,
                             walk_forward_summary=wf_summary, persistence_results=persist)
    with open(os.path.join(args.output, "market_priority_report.md"), "w") as fh:
        fh.write(md)

    audit_out = {
        "config": config, "audit": audit,
        "factors_used": factors, "macro_states_used": macro_cols,
        "n_rebalance_dates": len(rdates),
        "environment": {"python": platform.python_version(),
                        "pandas": pd.__version__, "numpy": np.__version__},
        "runtime_seconds": round(time.time() - t0, 2),
    }
    with open(os.path.join(args.output, "audit_trail.json"), "w") as fh:
        json.dump(audit_out, fh, indent=2, default=str)

    print(f"[done] outputs in ./{args.output} ({audit_out['runtime_seconds']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
