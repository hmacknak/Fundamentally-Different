#!/usr/bin/env python3
"""Pre-registered test of two order-flow rules on 1-minute bars.

1m OHLCV bars do not record trade direction, so order flow is ESTIMATED with
Bulk Volume Classification (Easley, Lopez de Prado and O'Hara 2012):
    buy_share_t = Phi(dp_t / sigma_t),  delta_t = volume_t * (2 * buy_share_t - 1)
where dp_t is the close-to-close change within the session and sigma_t is the
std of dp over the previous 390 bars (causal). The first bar of each session
gets delta 0.

Checkpoints: every 15 minutes from 10:00 to 15:30 ET. At a checkpoint bar i
(stamped at its start), signals use only bars before i. A trade enters at
bar i's open and exits at the close of bar i+14, so it lasts 15 minutes and
never overlaps the next one.

  H1 FLOW   order-flow momentum: side = sign(sum of delta over the 15 bars
            before i). Trades at every checkpoint.
  H2 DIV    delta divergence (absorption / exhaustion): if the close of bar
            i-1 is the highest close of the last 30 bars while their summed
            delta is negative -> short. If it is the lowest close while
            delta is positive -> long. No trade otherwise.

Costs: $0.005/share commission + $0.01/share slippage per side, the same
model as the earlier SPY tests. Data: Alpaca SIP 1m, adjustment=all, 2016+.

Statistic: per day, the mean net return of that day's trades. Days without
a trade are dropped. Newey-West (5 lags) one-sided t.

Pass rule (fixed before any result):
  1. SPY: Holm across H1 and H2 at family alpha 0.05 (net mean > 0).
  2. QQQ, IWM and DIA confirm: pooled per day (equal-weight across
     tickers), one-sided p < 0.05, and net mean > 0 on at least 2 of 3.
Gross (pre-cost) results are reported too, to show whether any predictive
signal exists before costs. They are descriptive only.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
from scipy.special import ndtr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "smc"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "edges"))
import backtest_smc as bt
import edge_family as ef

# ---- pre-registered protocol (do not edit after results are seen) --------
TICKERS = ("SPY", "QQQ", "IWM", "DIA")
PRIMARY = "SPY"
SIGMA_WINDOW = 390
SIGMA_MIN = 100
FLOW_LOOKBACK = 15
DIV_LOOKBACK = 30
HOLD = 15
CHECKPOINTS = [f"{h:02d}:{m:02d}" for h in range(10, 16) for m in (0, 15, 30, 45)
               if (h, m) <= (15, 30)]
COMMISSION = 0.005
SLIPPAGE = 0.01
FAMILY_ALPHA = 0.05
CONFIRM_ALPHA = 0.05
# ---------------------------------------------------------------------------


def bvc_delta(m: pd.DataFrame) -> pd.Series:
    """Bulk-volume-classified signed volume per bar (causal sigma)."""
    day = m.index.normalize()
    first = np.r_[True, day[1:] != day[:-1]]
    dp = m["close"].diff().where(~first)
    sigma = dp.rolling(SIGMA_WINDOW, min_periods=SIGMA_MIN).std().shift(1)
    z = (dp / sigma).replace([np.inf, -np.inf], np.nan)
    buy = pd.Series(ndtr(z.to_numpy()), index=z.index).where(np.isfinite(z), 0.5)
    return (m["volume"] * (2 * buy - 1)).fillna(0.0)


def trades(m: pd.DataFrame) -> pd.DataFrame:
    """One row per checkpoint per session per hypothesis (side 0 = no trade)."""
    delta = bvc_delta(m).to_numpy()
    o, c = m["open"].to_numpy(), m["close"].to_numpy()
    ts = m.index
    hhmm = ts.strftime("%H:%M")
    day = ts.normalize()
    pos = np.flatnonzero(np.isin(hhmm, CHECKPOINTS))
    rows = []
    n = len(m)
    for i in pos:
        if i - DIV_LOOKBACK < 0 or i + HOLD - 1 >= n:
            continue
        span_back = ts[i - 1] - ts[i - DIV_LOOKBACK]
        span_fwd = ts[i + HOLD - 1] - ts[i]
        # require complete, same-session minute windows
        if (day[i - DIV_LOOKBACK] != day[i] or day[i + HOLD - 1] != day[i]
                or span_back != pd.Timedelta(minutes=DIV_LOOKBACK - 1)
                or span_fwd != pd.Timedelta(minutes=HOLD - 1)):
            continue
        entry, exit_ = o[i], c[i + HOLD - 1]
        ret = exit_ / entry - 1
        cost = 2 * (COMMISSION + SLIPPAGE) / entry
        flow = delta[i - FLOW_LOOKBACK:i].sum()
        side1 = float(np.sign(flow))
        win = c[i - DIV_LOOKBACK:i]
        d30 = delta[i - DIV_LOOKBACK:i].sum()
        side2 = 0.0
        if c[i - 1] >= win.max() and d30 < 0:
            side2 = -1.0
        elif c[i - 1] <= win.min() and d30 > 0:
            side2 = 1.0
        for h, side in (("FLOW", side1), ("DIV", side2)):
            if side != 0:
                rows.append({"day": day[i].tz_localize(None), "time": hhmm[i], "hyp": h,
                             "side": side, "gross": side * ret,
                             "net": side * ret - cost})
    return pd.DataFrame(rows)


def daily_series(tr: pd.DataFrame, hyp: str, col: str = "net") -> pd.Series:
    t = tr[tr["hyp"] == hyp]
    return t.groupby("day")[col].mean()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--intraday-dir", required=True)
    ap.add_argument("--out", default="orderflow")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    all_tr = {}
    for tk in TICKERS:
        m = bt.load_csv(os.path.join(a.intraday_dir, f"{tk}.csv"))
        if (m["volume"] <= 0).mean() > 0.01:
            raise ValueError(f"{tk}: too many zero-volume bars for order-flow estimates")
        tr = trades(m)
        tr.to_csv(os.path.join(a.out, f"trades_{tk}.csv"), index=False)
        all_tr[tk] = tr

    rows = []
    for h in ("FLOW", "DIV"):
        for tk in TICKERS:
            tr = all_tr[tk][all_tr[tk]["hyp"] == h]
            net_d, gross_d = daily_series(all_tr[tk], h), daily_series(all_tr[tk], h, "gross")
            _, t_net, nd = ef.nw_t(net_d.to_numpy())
            _, t_gross, _ = ef.nw_t(gross_d.to_numpy())
            rows.append({"hyp": h, "ticker": tk, "trades": len(tr), "days": nd,
                         "hit_rate": (tr["net"] > 0).mean(),
                         "gross_bp": tr["gross"].mean() * 1e4, "gross_t": t_gross,
                         "net_bp": tr["net"].mean() * 1e4, "net_t": t_net,
                         "p_net": ef.p_one(t_net)})
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(a.out, "results.csv"), index=False)

    prim = res[res["ticker"] == PRIMARY].sort_values("p_net").reset_index(drop=True)
    rejected, m_h = set(), len(prim)
    for i, r in prim.iterrows():
        if r["net_bp"] > 0 and r["p_net"] < FAMILY_ALPHA / (m_h - i):
            rejected.add(r["hyp"])
        else:
            break
    verdicts = []
    others = [t for t in TICKERS if t != PRIMARY]
    for h in ("FLOW", "DIV"):
        pooled = pd.concat({tk: daily_series(all_tr[tk], h) for tk in others},
                           axis=1).mean(axis=1).dropna()
        mu, tp, _ = ef.nw_t(pooled.to_numpy())
        n_pos = int((res[(res["hyp"] == h) & (res["ticker"] != PRIMARY)]["net_bp"] > 0).sum())
        confirm = mu > 0 and ef.p_one(tp) < CONFIRM_ALPHA and n_pos >= 2
        verdicts.append({"hyp": h, "SPY_holm_reject": h in rejected,
                         "others_pooled_net_bp": mu * 1e4, "others_t": tp,
                         "others_positive": f"{n_pos}/3", "others_confirm": confirm,
                         "EDGE": (h in rejected) and confirm})
    vt = pd.DataFrame(verdicts)
    edges = vt.loc[vt["EDGE"], "hyp"].tolist()
    text = "\n".join([
        "Per ticker (bp per 15-minute trade; t-stats use per-day means, Newey-West):",
        res.to_string(index=False, float_format="%.3f"), "",
        vt.to_string(index=False, float_format="%.3f"), "",
        f"EDGES: {', '.join(edges)}" if edges else "EDGES: none"])
    print(text)
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("# Order flow (BVC estimate from 1m bars), pre-registered\n\n```\n"
                + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
