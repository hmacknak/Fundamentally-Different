#!/usr/bin/env python3
"""Pre-registered test of market intraday momentum (Gao, Han, Li and Zhou,
"Market Intraday Momentum", Journal of Financial Economics, 2018).

Rule (taken from the paper, nothing fitted on our data):
  r_first = previous session's close (15:59 bar close) -> 09:59 bar close
            (the overnight move plus the first half hour)
  At 15:30 (open of the 15:30 bar), go long 1x notional if r_first > 0,
  short if r_first < 0. Exit at the close (15:59 bar close). One trade
  per day, flat overnight.

Days without the needed bars (half-day sessions, gaps) or without a prior
session are skipped, never filled in. Costs per round trip are
2 x commission + 2 x slippage, in $/share, divided by the entry price.

Pass rule (fixed before any result; see docs/DECISIONS.md):
  1. SPY, full history: mean net daily return > 0 with HAC (Newey-West,
     5 lags) one-sided p < 0.05.
  2. QQQ, IWM, DIA pooled (equal-weight across tickers per day, which
     clusters by day): mean net return > 0 with HAC one-sided p < 0.05,
     and net mean > 0 on at least 2 of the 3.
  3. SPY over the last 12 months: net mean > 0 (a sign check only;
     a single year has too little power for a significance test).
  An edge is claimed only if all three hold.

Example:
  python playground/momentum/intraday_momentum.py SPY=spy.csv QQQ=qqq.csv \\
      IWM=iwm.csv DIA=dia.csv --out momentum
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "smc"))
import backtest_smc as bt

# ---- pre-registered protocol (do not edit after results are seen) --------
SIGNAL_BAR = "09:59"  # close of this bar ends the first half hour
ENTRY_BAR = "15:30"  # enter at this bar's open
EXIT_BAR = "15:59"  # exit at this bar's close
COMMISSION = 0.005  # $/share/side
SLIPPAGE = 0.01  # $/share/side
HAC_LAGS = 5
ALPHA = 0.05
HOLDOUT_MONTHS = 12
PRIMARY = "SPY"
# ---------------------------------------------------------------------------


def daily_trades(df: pd.DataFrame) -> pd.DataFrame:
    """One row per session that has all needed bars: signal, returns, P&L."""
    hhmm = df.index.strftime("%H:%M")
    day = df.index.normalize()
    frame = pd.DataFrame({"day": day, "hhmm": hhmm, "open": df["open"].to_numpy(),
                          "close": df["close"].to_numpy()})
    last_close = frame.groupby("day")["close"].last()
    sig = frame[frame["hhmm"] == SIGNAL_BAR].set_index("day")["close"]
    entry = frame[frame["hhmm"] == ENTRY_BAR].set_index("day")["open"]
    exit_ = frame[frame["hhmm"] == EXIT_BAR].set_index("day")["close"]
    prev_close = last_close.shift(1)
    # a session only counts as the "previous close" if it ran to 15:59
    full_days = set(exit_.index)
    prev_full = pd.Series([d in full_days for d in last_close.index],
                          index=last_close.index).shift(1, fill_value=False)
    out = pd.DataFrame({"prev_close": prev_close.where(prev_full), "sig_close": sig,
                        "entry": entry, "exit": exit_}).dropna()
    out["r_first"] = out["sig_close"] / out["prev_close"] - 1
    out = out[out["r_first"] != 0]
    out["side"] = np.sign(out["r_first"])
    out["gross"] = out["side"] * (out["exit"] / out["entry"] - 1)
    cost = (2 * COMMISSION + 2 * SLIPPAGE) / out["entry"]
    out["net"] = out["gross"] - cost
    out["r_last"] = out["exit"] / out["entry"] - 1
    out.index.name = "day"
    return out


def hac_t(x: pd.Series, lags: int = HAC_LAGS) -> float:
    """t-stat of the mean with a Newey-West (Bartlett) variance."""
    x = pd.Series(x).dropna().to_numpy(float)
    n = len(x)
    if n < 3:
        return math.nan
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        var += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(var / n)) if var > 0 else math.nan


def p_one_sided(t: float) -> float:
    return 1 - NormalDist().cdf(t) if math.isfinite(t) else 1.0


def stats(tr: pd.DataFrame, col: str = "net") -> dict:
    x = tr[col]
    n = len(x)
    sd = x.std(ddof=1)
    t = hac_t(x)
    slope = (np.polyfit(tr["r_first"], tr["r_last"], 1)[0] if n > 2 else math.nan)
    return {"days": n, "hit_rate": float((x > 0).mean()) if n else math.nan,
            "mean_bp": float(x.mean() * 1e4) if n else math.nan,
            "gross_mean_bp": float(tr["gross"].mean() * 1e4) if n else math.nan,
            "ann_sharpe": float(x.mean() / sd * math.sqrt(252)) if n > 1 and sd > 0
            else math.nan,
            "hac_t": t, "p_one_sided": p_one_sided(t),
            "total_return_pct": float(((1 + x).prod() - 1) * 100) if n else math.nan,
            "slope_r_last_on_r_first": float(slope)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="TICKER=path.csv (1m bars)")
    ap.add_argument("--out", default="momentum")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    trades: dict[str, pd.DataFrame] = {}
    for item in a.inputs:
        ticker, path = item.split("=", 1)
        tr = daily_trades(bt.load_csv(path))
        if tr.empty:
            print(f"error: no usable sessions for {ticker}", file=sys.stderr)
            return 1
        tr.to_csv(os.path.join(a.out, f"days_{ticker}.csv"))
        trades[ticker] = tr
    if PRIMARY not in trades:
        print(f"error: {PRIMARY} is required", file=sys.stderr)
        return 2

    rows = [{"ticker": tk, "first_day": f"{tr.index[0]:%Y-%m-%d}",
             "last_day": f"{tr.index[-1]:%Y-%m-%d}", **stats(tr)}
            for tk, tr in trades.items()]
    spy = trades[PRIMARY]
    split = (spy.index[-1] - pd.DateOffset(months=HOLDOUT_MONTHS)).normalize()
    recent = spy[spy.index >= split]
    rows.append({"ticker": f"{PRIMARY} last {HOLDOUT_MONTHS}m",
                 "first_day": f"{recent.index[0]:%Y-%m-%d}",
                 "last_day": f"{recent.index[-1]:%Y-%m-%d}", **stats(recent)})

    others = [tk for tk in trades if tk != PRIMARY]
    t1 = stats(spy)
    pass1 = t1["mean_bp"] > 0 and t1["p_one_sided"] < ALPHA
    pass2, pooled_line = False, "no other tickers supplied"
    if others:
        pooled = pd.concat({tk: trades[tk]["net"] for tk in others}, axis=1).mean(axis=1)
        tp = hac_t(pooled)
        n_pos = sum(trades[tk]["net"].mean() > 0 for tk in others)
        pass2 = pooled.mean() > 0 and p_one_sided(tp) < ALPHA and n_pos >= 2
        pooled_line = (f"{'+'.join(others)} pooled: {len(pooled)} days, mean "
                       f"{pooled.mean() * 1e4:+.2f} bp/day, HAC t {tp:+.2f}, "
                       f"p {p_one_sided(tp):.3f}; positive on {n_pos}/{len(others)}")
    pass3 = recent["net"].mean() > 0
    edge = pass1 and pass2 and pass3
    table = pd.DataFrame(rows).to_string(index=False, float_format="%.3f")
    text = "\n".join([
        table, "", pooled_line, "",
        f"1. {PRIMARY} full history significant: {'PASS' if pass1 else 'FAIL'} "
        f"(mean {t1['mean_bp']:+.2f} bp/day, HAC t {t1['hac_t']:+.2f}, "
        f"p {t1['p_one_sided']:.3f})",
        f"2. Other ETFs confirm: {'PASS' if pass2 else 'FAIL'}",
        f"3. {PRIMARY} last {HOLDOUT_MONTHS} months positive: "
        f"{'PASS' if pass3 else 'FAIL'} ({recent['net'].mean() * 1e4:+.2f} bp/day)",
        "",
        "EDGE FOUND (all three pre-registered tests passed)" if edge else
        "NO EDGE (not all pre-registered tests passed)"])
    print(text)
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("# Market intraday momentum (pre-registered)\n\n```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
