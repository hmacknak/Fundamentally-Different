#!/usr/bin/env python3
"""Pre-registered confirmation test: run ONE locked variant, unchanged, on
other tickers' full history. Each ticker is out-of-sample because the variant
was chosen on SPY in-sample data only (see docs/DECISIONS.md).

Pass rule (fixed before any result):
  - pooled net R > 0 with one-sided p < 0.05, using day-clustered t-stats
    (all trades on the same date are summed first, because these ETFs move
    together and per-trade t-stats would overstate the evidence), AND
  - net R per trade > 0 on at least 2 of the 3 tickers.

Example:
  python playground/smc/confirm_smc.py QQQ=qqq.csv IWM=iwm.csv DIA=dia.csv
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import replace
from statistics import NormalDist

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_smc as bt

# ---- locked variant and pass rule (do not edit after results are seen) ----
VARIANT = {"tf": 5, "swing_n": 3, "rr": 1.0, "entry_start": "09:35", "vwap_filter": False}
ALPHA = 0.05
MIN_POSITIVE = 2
# ---------------------------------------------------------------------------


def locked_params() -> bt.Params:
    p = bt.params_for_tf(bt.Params(), VARIANT["tf"])
    return replace(p, swing_n=VARIANT["swing_n"], rr=VARIANT["rr"],
                   entry_start=VARIANT["entry_start"], vwap_filter=VARIANT["vwap_filter"])


def day_clustered_t(trades: pd.DataFrame) -> tuple[float, int]:
    if trades.empty:
        return math.nan, 0
    daily = trades.groupby(pd.to_datetime(trades["entry_time"]).dt.date)["net_r"].sum()
    n = len(daily)
    sd = daily.std(ddof=1) if n > 1 else math.nan
    return (float(daily.mean() / sd * math.sqrt(n)) if sd and sd > 0 else math.nan), n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="TICKER=path.csv")
    ap.add_argument("--out", default="confirm")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    p = locked_params()
    rows, all_trades = [], []
    for item in a.inputs:
        ticker, path = item.split("=", 1)
        bars = bt.resample(bt.load_csv(path), VARIANT["tf"])
        tr = bt.backtest(bars, p).assign(ticker=ticker)
        tr.to_csv(os.path.join(a.out, f"trades_{ticker}.csv"), index=False)
        all_trades.append(tr)
        s = bt.summarize(tr, p)
        t_day, n_days = day_clustered_t(tr)
        rows.append({"ticker": ticker, "sessions": bars.index.normalize().nunique(),
                     **{k: s.get(k) for k in ("trades", "win_rate", "avg_gross_r",
                                              "avg_net_r", "max_dd_pct")},
                     "t_day_clustered": t_day})
    pooled = pd.concat(all_trades, ignore_index=True)
    t_pool, n_days = day_clustered_t(pooled)
    p_pool = 1 - NormalDist().cdf(t_pool) if math.isfinite(t_pool) else 1.0
    n_pos = sum(1 for r in rows if (r["avg_net_r"] or 0) > 0)
    passed = (pooled["net_r"].mean() > 0 and p_pool < ALPHA and n_pos >= MIN_POSITIVE)
    table = pd.DataFrame(rows).to_string(index=False, float_format="%.3f")
    verdict = "CONFIRMED" if passed else "NOT CONFIRMED"
    text = (f"Locked variant: {VARIANT}\n\n{table}\n\n"
            f"Pooled: {len(pooled)} trades on {n_days} days, net R/trade "
            f"{pooled['net_r'].mean():+.3f}, day-clustered t {t_pool:+.2f}, "
            f"one-sided p {p_pool:.3f}. Positive tickers: {n_pos}/{len(rows)}.\n\n"
            f"{verdict} (needs p < {ALPHA} and >= {MIN_POSITIVE} positive tickers)")
    print(text)
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("# Cross-ticker confirmation (pre-registered)\n\n```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
