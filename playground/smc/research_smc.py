#!/usr/bin/env python3
"""Pre-registered variant search for the BOS/CHoCH retest strategy.

The protocol is fixed in this file (GRID, MIN_TRADES, TOP_K and the pass
rules), committed before any result is seen, and recorded in
docs/DECISIONS.md:

  1. Run every variant in GRID on the in-sample period only (everything
     before the last `--holdout-months`).
  2. Rank variants with at least MIN_TRADES trades by the t-stat of net R
     per trade. Compare the best t to the expected maximum t of N variants
     with no edge at all (the deflation benchmark, N = len(GRID)).
  3. Run the TOP_K variants, unchanged, once on the holdout.
  4. An edge is claimed only if a variant (a) beats the deflation benchmark
     in-sample AND (b) on the holdout has positive net R with a one-sided
     p-value below 0.05 / TOP_K.

Example:
  python playground/smc/research_smc.py spy_1min.csv --out research
"""
from __future__ import annotations

import argparse
import itertools
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from statistics import NormalDist

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_smc as bt

# ---- pre-registered protocol (do not edit after results are seen) --------
SWINGS = {1: (3, 5, 8), 5: (2, 3, 5)}  # fractal size per timeframe
RRS = (1.0, 1.5, 2.0)
ENTRY_STARTS = ("09:35", "10:00")
VWAP = (False, True)
GRID = [{"tf": tf, "swing_n": n, "rr": rr, "entry_start": es, "vwap_filter": vw}
        for tf in (1, 5)
        for n, rr, es, vw in itertools.product(SWINGS[tf], RRS, ENTRY_STARTS, VWAP)]
MIN_TRADES = 100
TOP_K = 3
ALPHA = 0.05
# ---------------------------------------------------------------------------

_BARS: dict[int, pd.DataFrame] = {}


def expected_max_t(n: int) -> float:
    """Expected maximum of n independent standard normals (Bailey and
    Lopez de Prado's approximation). This is what the best of n no-edge
    variants scores by luck alone. Correlated variants make it conservative."""
    if n <= 1:
        return 0.0
    g = 0.5772156649
    z = NormalDist().inv_cdf
    return (1 - g) * z(1 - 1 / n) + g * z(1 - 1 / (n * math.e))


def one_sided_p(t: float) -> float:
    return 1 - NormalDist().cdf(t) if math.isfinite(t) else 1.0


def variant_params(v: dict) -> bt.Params:
    p = bt.params_for_tf(bt.Params(), v["tf"])
    return replace(p, swing_n=v["swing_n"], rr=v["rr"], entry_start=v["entry_start"],
                   vwap_filter=v["vwap_filter"])


def _run(v: dict) -> dict:
    p = variant_params(v)
    s = bt.summarize(bt.backtest(_BARS[v["tf"]], p), p)
    return {**v, **s}


def _init(bars: dict[int, pd.DataFrame]) -> None:
    _BARS.clear()
    _BARS.update(bars)


def run_grid(df1: pd.DataFrame, variants: list[dict], workers: int) -> pd.DataFrame:
    bars = {tf: bt.resample(df1, tf) for tf in sorted({v["tf"] for v in variants})}
    if workers <= 1:
        _init(bars)
        rows = [_run(v) for v in variants]
    else:
        with ProcessPoolExecutor(workers, initializer=_init, initargs=(bars,)) as ex:
            rows = list(ex.map(_run, variants))
    return pd.DataFrame(rows)


def label(v) -> str:
    return (f"{v['tf']}m n={v['swing_n']} rr={v['rr']} start={v['entry_start']} "
            f"vwap={'on' if v['vwap_filter'] else 'off'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--holdout-months", type=int, default=12)
    ap.add_argument("--out", default="research")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--grid-limit", type=int, default=0, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    df = bt.load_csv(a.csv)
    last = df.index[-1]
    split = (last - pd.DateOffset(months=a.holdout_months)).normalize()
    ins, hold = df[df.index < split], df[df.index >= split]
    if ins.empty or hold.empty:
        print("error: need data on both sides of the holdout split", file=sys.stderr)
        return 1
    grid = GRID[:a.grid_limit] if a.grid_limit else GRID
    n = len(grid)
    bench = expected_max_t(n)
    lines = [
        "# BOS/CHoCH variant search (pre-registered)",
        "",
        f"- In-sample: {ins.index[0]:%Y-%m-%d} .. {ins.index[-1]:%Y-%m-%d} "
        f"({ins.index.normalize().nunique()} sessions)",
        f"- Holdout: {hold.index[0]:%Y-%m-%d} .. {hold.index[-1]:%Y-%m-%d} "
        f"({hold.index.normalize().nunique()} sessions)",
        f"- Variants tested in-sample: {n}. Expected best t from luck alone: {bench:.2f}",
        f"- Holdout bar: net R > 0 and one-sided p < {ALPHA}/{TOP_K} "
        f"(t > {NormalDist().inv_cdf(1 - ALPHA / TOP_K):.2f})",
        "",
    ]
    print("\n".join(lines))

    res = run_grid(ins, grid, a.workers)
    res = res.sort_values("t_stat", ascending=False, na_position="last")
    res.to_csv(os.path.join(a.out, "in_sample_grid.csv"), index=False)
    eligible = res[res["trades"] >= MIN_TRADES]
    cols = ["tf", "swing_n", "rr", "entry_start", "vwap_filter", "trades", "win_rate",
            "avg_gross_r", "avg_net_r", "t_stat", "max_dd_pct"]
    top_table = eligible[cols].head(15).to_string(index=False, float_format="%.3f")
    print(f"In-sample, top 15 of {len(eligible)} variants with >= {MIN_TRADES} trades:")
    print(top_table)
    frac_pos = float((eligible["avg_net_r"] > 0).mean()) if len(eligible) else math.nan
    print(f"\nShare of eligible variants with positive net R: {frac_pos:.0%}")
    lines += ["## In-sample (top 15)", "", "```", top_table, "```", "",
              f"Share of eligible variants with positive net R: {frac_pos:.0%}", ""]

    picks = eligible.head(TOP_K).to_dict("records")
    t_bar = NormalDist().inv_cdf(1 - ALPHA / TOP_K)
    hold_rows = run_grid(hold, [{k: v[k] for k in GRID[0]} for v in picks], a.workers)
    verdicts = []
    for v, h in zip(picks, hold_rows.to_dict("records"), strict=True):
        ins_pass = v["t_stat"] > bench
        hold_pass = h.get("trades", 0) > 0 and h["avg_net_r"] > 0 and h["t_stat"] > t_bar
        verdicts.append({
            "variant": label(v), "ins_trades": v["trades"], "ins_net_r": v["avg_net_r"],
            "ins_t": v["t_stat"], "ins_beats_luck": ins_pass,
            "hold_trades": h.get("trades", 0), "hold_net_r": h.get("avg_net_r"),
            "hold_t": h.get("t_stat"), "hold_p": one_sided_p(h.get("t_stat", math.nan)),
            "hold_pass": hold_pass, "EDGE": ins_pass and hold_pass})
    vt = pd.DataFrame(verdicts)
    vt.to_csv(os.path.join(a.out, "holdout_verdicts.csv"), index=False)
    vtable = vt.to_string(index=False, float_format="%.3f")
    any_edge = bool(vt["EDGE"].any()) if len(vt) else False
    verdict = ("EDGE FOUND: at least one variant passed both pre-registered tests."
               if any_edge else
               "NO EDGE: no variant passed both pre-registered tests.")
    print(f"\nHoldout check of the top {TOP_K}:\n{vtable}\n\n{verdict}")
    lines += [f"## Holdout check (top {TOP_K}, run once)", "", "```", vtable, "```", "",
              f"**{verdict}**", "",
              "Params of each pick: " + "; ".join(
                  str({k: v for k, v in asdict(variant_params(p)).items()
                       if k in ('swing_n', 'rr', 'entry_start', 'vwap_filter',
                                'min_risk', 'max_risk', 'max_armed_bars')})
                  for p in picks)]
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
