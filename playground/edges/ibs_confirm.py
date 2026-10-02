#!/usr/bin/env python3
"""Pre-registered out-of-sample confirmation of the IBS reversal effect on
equity-index ETFs never used in any earlier test.

H3 IBS was the only family hypothesis positive on all four original ETFs
(see docs/DECISIONS.md). Here the identical rule (edge_family.h_ibs: IBS <
0.2, buy at the close, sell at the next close, 1 bp per side) runs unchanged
on a fixed basket of new ETFs, over the same post-publication period (2014+).

Pass rule (fixed before any result):
  - pooled across the basket, per day: the mean signal-day excess return
    (net of costs, minus that ETF's non-signal-day mean) > 0 with
    Newey-West one-sided p < 0.05, AND
  - the effect is positive on at least 2/3 of the basket.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge_family as ef

# ---- pre-registered protocol (do not edit after results are seen) --------
BASKET = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "EFA", "EEM")
START = "2014-01-01"
ALPHA = 0.05
MIN_POSITIVE_SHARE = 2 / 3
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--daily-dir", required=True)
    ap.add_argument("--out", default="ibs_confirm")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rows, parts = [], []
    for tk in BASKET:
        f = ef.h_ibs(ef.load_daily(os.path.join(a.daily_dir, f"{tk}.csv")))
        f = f[f.index >= pd.Timestamp(START)]
        b, t, n = ef.effect(f)
        rows.append({"ticker": tk, "obs": n, "signal_days": int(f["active"].sum()),
                     "effect_bp": b * 1e4, "t": t})
        base = f.loc[f["x"] == 0, "y"].mean()
        parts.append((f["y"] - base).where(f["x"] == 1).rename(tk))
    series = pd.concat(parts, axis=1).mean(axis=1).dropna()
    mean, tp, n_days = ef.nw_t(series.to_numpy())
    res = pd.DataFrame(rows)
    share_pos = float((res["effect_bp"] > 0).mean())
    passed = mean > 0 and ef.p_one(tp) < ALPHA and share_pos >= MIN_POSITIVE_SHARE
    text = "\n".join([
        res.to_string(index=False, float_format="%.3f"), "",
        f"Pooled: {n_days} signal days, mean excess {mean * 1e4:+.2f} bp, "
        f"Newey-West t {tp:+.2f}, one-sided p {ef.p_one(tp):.4f}; "
        f"positive on {share_pos:.0%} of the basket", "",
        "CONFIRMED" if passed else "NOT CONFIRMED"])
    print(text)
    res.to_csv(os.path.join(a.out, "per_ticker.csv"), index=False)
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("# IBS out-of-sample confirmation (pre-registered)\n\n```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
