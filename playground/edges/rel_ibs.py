#!/usr/bin/env python3
"""Pre-registered test of RELATIVE (sector-specific) IBS reversal.

Hypothesis, formed from the 2014+ IBS confirmation run: the IBS reversal
comes from sector-specific weak closes, not market-wide ones. To keep it
honest it is tested ONLY on data that no earlier run touched: the nine
sector SPDRs from their 1999 launch through 2013.

Rule: a sector ETF signals when its IBS < 0.2 while SPY's IBS >= 0.2 on the
same day. Buy that ETF at the close, sell at the next close. Costs are
2 bp per side, higher than before to reflect the wider spreads of 1999-2013.

Pass rule (fixed before any result):
  - pooled per day: the mean signal-day excess return (net of costs, minus
    that ETF's non-signal-day mean) > 0 with Newey-West one-sided p < 0.05,
    AND
  - the effect is positive on at least 6 of the 9 sectors.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge_family as ef

# ---- pre-registered protocol (do not edit after results are seen) --------
SECTORS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY")
MARKET = "SPY"
START, END = "1999-01-01", "2013-12-31"
IBS_LOW = 0.2
COST_BP = 2.0
ALPHA = 0.05
MIN_POSITIVE = 6
# ---------------------------------------------------------------------------


def ibs(d: pd.DataFrame) -> pd.Series:
    rng = d["high"] - d["low"]
    return ((d["close"] - d["low"]) / rng).where(rng > 0)


def sector_frame(sec: pd.DataFrame, mkt: pd.DataFrame) -> pd.DataFrame:
    m_ibs = ibs(mkt).reindex(sec.index)
    sig_today = (ibs(sec) < IBS_LOW) & (m_ibs >= IBS_LOW)
    signal = sig_today.shift(1, fill_value=False)  # acts on the next day's return
    r = sec["close"].pct_change()
    y = np.where(signal, r - 2 * COST_BP / 1e4, r)
    f = pd.DataFrame({"y": y, "x": signal.astype(float), "active": signal}, index=sec.index)
    return f[(f.index >= pd.Timestamp(START)) & (f.index <= pd.Timestamp(END))].iloc[1:]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--daily-dir", required=True)
    ap.add_argument("--out", default="rel_ibs")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    mkt = ef.load_daily(os.path.join(a.daily_dir, f"{MARKET}.csv"))
    rows, parts = [], []
    for tk in SECTORS:
        f = sector_frame(ef.load_daily(os.path.join(a.daily_dir, f"{tk}.csv")), mkt)
        b, t, n = ef.effect(f)
        rows.append({"ticker": tk, "from": f"{f.index[0]:%Y-%m-%d}",
                     "to": f"{f.index[-1]:%Y-%m-%d}", "obs": n,
                     "signal_days": int(f["active"].sum()), "effect_bp": b * 1e4, "t": t})
        base = f.loc[f["x"] == 0, "y"].mean()
        parts.append((f["y"] - base).where(f["x"] == 1).rename(tk))
    series = pd.concat(parts, axis=1).mean(axis=1).dropna()
    mean, tp, n_days = ef.nw_t(series.to_numpy())
    res = pd.DataFrame(rows)
    n_pos = int((res["effect_bp"] > 0).sum())
    passed = mean > 0 and ef.p_one(tp) < ALPHA and n_pos >= MIN_POSITIVE
    text = "\n".join([
        res.to_string(index=False, float_format="%.3f"), "",
        f"Pooled: {n_days} signal days, mean excess {mean * 1e4:+.2f} bp, "
        f"Newey-West t {tp:+.2f}, one-sided p {ef.p_one(tp):.4f}; "
        f"positive on {n_pos}/{len(SECTORS)}", "",
        "CONFIRMED" if passed else "NOT CONFIRMED"])
    print(text)
    res.to_csv(os.path.join(a.out, "per_sector.csv"), index=False)
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("# Relative IBS, untouched 1999-2013 sample (pre-registered)\n\n```\n"
                + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
