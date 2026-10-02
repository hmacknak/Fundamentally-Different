#!/usr/bin/env python3
"""Pre-registered EXECUTABLE test of relative IBS on recent minute data.

The 1999-2013 test computed IBS from the official close and traded at that
same close, which cannot be done live. Here the signal uses only bars before
15:50 ET, the closing-auction (MOC) order cutoff:

  IBS_1550 = (last close before 15:50 - day low) / (day high - day low),
             with high and low taken over 09:30-15:49.
  Signal:    sector IBS_1550 < 0.2 AND SPY IBS_1550 >= 0.2.
  Trade:     buy at the close (15:59 bar close, a proxy for the auction
             price), sell at the next session's close. 1 bp per side.

Sessions missing the 15:49 or 15:59 bar (half days) are skipped.

Data: Alpaca SIP 1m, 2016 onward. This period overlaps the 2014+ data the
hypothesis was formed from, so this run checks the rule is still alive and
executable. It is not an independent discovery test.

Pass rule (fixed before any result):
  - pooled per day: the mean signal-day excess return (net, minus that ETF's
    non-signal close-to-close mean) > 0 with Newey-West one-sided p < 0.05,
    AND
  - the effect is positive on at least 6 of the 9 sectors.
A portfolio summary (equal weight across signalling sectors each day) is
reported for information only.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "smc"))
import backtest_smc as bt
import edge_family as ef

# ---- pre-registered protocol (do not edit after results are seen) --------
SECTORS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY")
MARKET = "SPY"
CUTOFF = "15:50"
CLOSE_BAR = "15:59"
IBS_LOW = 0.2
COST_BP = 1.0
ALPHA = 0.05
MIN_POSITIVE = 6
# ---------------------------------------------------------------------------


def daily_from_minutes(m: pd.DataFrame) -> pd.DataFrame:
    """Per session: high/low/last before the cutoff, plus the close-bar close."""
    hhmm = m.index.strftime("%H:%M")
    day = m.index.normalize().tz_localize(None)
    pre = hhmm < CUTOFF
    g = pd.DataFrame({"day": day[pre], "high": m["high"].to_numpy()[pre],
                      "low": m["low"].to_numpy()[pre], "close": m["close"].to_numpy()[pre],
                      "hhmm": hhmm[pre]}).groupby("day")
    out = pd.DataFrame({"hi": g["high"].max(), "lo": g["low"].min(),
                        "last": g["close"].last(), "last_hhmm": g["hhmm"].last()})
    closes = pd.Series(m["close"].to_numpy()[hhmm == CLOSE_BAR],
                       index=day[hhmm == CLOSE_BAR])
    out["close"] = closes
    out = out[out["last_hhmm"] == "15:49"].dropna(subset=["close"])
    rng = out["hi"] - out["lo"]
    out["ibs"] = ((out["last"] - out["lo"]) / rng).where(rng > 0)
    return out


def sector_frame(sec: pd.DataFrame, mkt: pd.DataFrame) -> pd.DataFrame:
    m_ibs = mkt["ibs"].reindex(sec.index)
    sig_today = (sec["ibs"] < IBS_LOW) & (m_ibs >= IBS_LOW)
    signal = sig_today.shift(1, fill_value=False)
    r = sec["close"].pct_change()
    y = np.where(signal, r - 2 * COST_BP / 1e4, r)
    f = pd.DataFrame({"y": y, "x": signal.astype(float), "active": signal}, index=sec.index)
    return f.iloc[1:]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--intraday-dir", required=True)
    ap.add_argument("--out", default="rel_ibs_live")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    mkt = daily_from_minutes(bt.load_csv(os.path.join(a.intraday_dir, f"{MARKET}.csv")))
    rows, parts, pnl = [], [], []
    for tk in SECTORS:
        sec = daily_from_minutes(bt.load_csv(os.path.join(a.intraday_dir, f"{tk}.csv")))
        f = sector_frame(sec, mkt)
        b, t, n = ef.effect(f)
        rows.append({"ticker": tk, "from": f"{f.index[0]:%Y-%m-%d}",
                     "to": f"{f.index[-1]:%Y-%m-%d}", "obs": n,
                     "signal_days": int(f["active"].sum()), "effect_bp": b * 1e4, "t": t})
        base = f.loc[f["x"] == 0, "y"].mean()
        parts.append((f["y"] - base).where(f["x"] == 1).rename(tk))
        pnl.append(f["y"].where(f["x"] == 1).rename(tk))
    series = pd.concat(parts, axis=1).mean(axis=1).dropna()
    mean, tp, n_days = ef.nw_t(series.to_numpy())
    res = pd.DataFrame(rows)
    n_pos = int((res["effect_bp"] > 0).sum())
    passed = mean > 0 and ef.p_one(tp) < ALPHA and n_pos >= MIN_POSITIVE

    port = pd.concat(pnl, axis=1).mean(axis=1).fillna(0.0)  # flat on no-signal days
    eq = (1 + port).cumprod()
    years = max((port.index[-1] - port.index[0]).days / 365.25, 1e-9)
    sd = port.std(ddof=1)
    info = (f"Portfolio (equal weight across signalling sectors, flat otherwise): "
            f"CAGR {(eq.iloc[-1] ** (1 / years) - 1) * 100:+.2f}%, "
            f"Sharpe {port.mean() / sd * math.sqrt(252) if sd > 0 else float('nan'):.2f}, "
            f"max DD {(eq / eq.cummax() - 1).min() * 100:.1f}%, "
            f"in market {(port != 0).mean():.0%} of days")
    text = "\n".join([
        res.to_string(index=False, float_format="%.3f"), "",
        f"Pooled: {n_days} signal days, mean excess {mean * 1e4:+.2f} bp, "
        f"Newey-West t {tp:+.2f}, one-sided p {ef.p_one(tp):.4f}; "
        f"positive on {n_pos}/{len(SECTORS)}", "", info, "",
        "CONFIRMED" if passed else "NOT CONFIRMED"])
    print(text)
    res.to_csv(os.path.join(a.out, "per_sector.csv"), index=False)
    port.rename("ret").to_csv(os.path.join(a.out, "portfolio_daily.csv"))
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("# Relative IBS, executable 15:50 signal, 2016+ (pre-registered)\n\n```\n"
                + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
