#!/usr/bin/env python3
"""Pre-registered family test of published return anomalies on US index ETFs.

Each hypothesis is one fixed rule taken from its source paper, with nothing
fitted on our data. Evidence comes from POST-PUBLICATION data, which the
authors could not have seen. All tests are corrected together with Holm's
method, so trying several ideas does not inflate the false-positive rate.

  H1 TOM   turn of the month (Lakonishok and Smidt 1988; McConnell and Xu
           2008). Long the last trading day of the month and the first 3 of
           the next. Effect = mean TOM-day return minus mean other-day return.
           Post-publication period: 2009+.
  H2 OVN   overnight drift (Cliff, Cooper and Gulen 2008; Lou, Polk and
           Skouras 2019). Hold close -> next open. Effect = overnight return
           net of costs minus the same day's intraday (open -> close) return.
           Post-publication period: 2009+.
  H3 IBS   internal bar strength reversal (Pagonidis 2013). IBS = (C-L)/(H-L).
           Buy at the close when IBS < 0.2, sell at the next close. Effect =
           next-day return after a signal, net of costs, minus next-day
           return otherwise. Post-publication period: 2014+.
  H4 IMHV  intraday momentum on volatile days (Gao, Han, Li and Zhou 2018;
           volatility conditioning). Same rule as playground/momentum, traded
           only when |r_first| is above the 2/3 quantile of the previous 252
           tradable days. Effect = net return per trade. Data: Alpaca 1m,
           2016+ (all of it is post-publication of the base effect).

Costs: COST_BP per side, on every entry and exit.

Pass rule (fixed before any result):
  - SPY post-publication, one-sided Newey-West p-values across H1-H4, with
    Holm correction at family alpha 0.05.
  - A rejected hypothesis counts as an edge only if the other ETFs also
    confirm it: pooled per day, one-sided p < 0.05, and the effect is
    positive on at least 2 of QQQ, IWM and DIA.

Example:
  python playground/edges/edge_family.py --daily-dir data/daily \\
      --intraday-dir data/intraday --out edges
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "momentum"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "smc"))
import backtest_smc as bt
import intraday_momentum as im

# ---- pre-registered protocol (do not edit after results are seen) --------
TICKERS = ("SPY", "QQQ", "IWM", "DIA")
PRIMARY = "SPY"
COST_BP = 1.0  # per side
POST_PUB = {"TOM": "2009-01-01", "OVN": "2009-01-01", "IBS": "2014-01-01",
            "IMHV": "2016-01-01"}
TOM_AFTER = 3  # first N trading days of the new month
IBS_THRESHOLD = 0.2
IMHV_WINDOW = 252
IMHV_QUANTILE = 2 / 3
HAC_LAGS = 5
FAMILY_ALPHA = 0.05
CONFIRM_ALPHA = 0.05
# ---------------------------------------------------------------------------
COST = COST_BP / 1e4


def nw_t(y: np.ndarray, x: np.ndarray | None = None, lags: int = HAC_LAGS) -> tuple:
    """OLS of y on [1, x] (or on 1 alone) with Newey-West errors.
    Returns (coefficient of interest, t-stat, n)."""
    y = np.asarray(y, float)
    X = np.ones((len(y), 1)) if x is None else np.column_stack([np.ones(len(y)), x])
    ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
    y, X = y[ok], X[ok]
    n, k = X.shape
    if n <= k + 2:
        return math.nan, math.nan, n
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for lag in range(1, min(lags, n - 1) + 1):
        w = 1 - lag / (lags + 1)
        G = Xu[lag:].T @ Xu[:-lag]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    j = k - 1
    se = math.sqrt(V[j, j]) if V[j, j] > 0 else math.nan
    return float(b[j]), float(b[j] / se) if se else math.nan, n


def p_one(t: float) -> float:
    return 1 - NormalDist().cdf(t) if math.isfinite(t) else 1.0


# ---- daily hypotheses: each returns a per-day frame with "effect" inputs --
def h_tom(d: pd.DataFrame) -> pd.DataFrame:
    r = d["close"].pct_change()
    month = d.index.to_period("M")
    pos_in_month = pd.Series(1, index=d.index).groupby(month).cumsum()
    left_in_month = pd.Series(1, index=d.index)[::-1].groupby(month[::-1]).cumsum()[::-1]
    tom = (left_in_month == 1) | (pos_in_month <= TOM_AFTER)
    # one round trip per month: charge entry on the first TOM day, exit on the last
    starts = tom & ~tom.shift(1, fill_value=False)
    ends = tom & ~tom.shift(-1, fill_value=False)
    net = r - COST * starts.astype(float) - COST * ends.astype(float)
    y = np.where(tom, net, r)
    return pd.DataFrame({"y": y, "x": tom.astype(float), "active": tom}, index=d.index)


def h_ovn(d: pd.DataFrame) -> pd.DataFrame:
    overnight = d["open"] / d["close"].shift(1) - 1 - 2 * COST
    intraday = d["close"] / d["open"] - 1
    return pd.DataFrame({"y": overnight - intraday, "x": np.nan, "active": True,
                         "overnight_net": overnight, "intraday": intraday},
                        index=d.index)


def h_ibs(d: pd.DataFrame) -> pd.DataFrame:
    rng = d["high"] - d["low"]
    ibs = ((d["close"] - d["low"]) / rng).where(rng > 0)
    signal = (ibs < IBS_THRESHOLD).shift(1, fill_value=False)  # known at prior close
    r = d["close"].pct_change()
    y = np.where(signal, r - 2 * COST, r)
    return pd.DataFrame({"y": y, "x": signal.astype(float), "active": signal},
                        index=d.index)


DAILY = {"TOM": h_tom, "OVN": h_ovn, "IBS": h_ibs}


def effect(frame: pd.DataFrame) -> tuple[float, float, int]:
    """TOM/IBS: coefficient on the active dummy. OVN/IMHV: mean of y."""
    if frame["x"].isna().all():
        return nw_t(frame["y"].to_numpy())
    return nw_t(frame["y"].to_numpy(), frame["x"].to_numpy())


def imhv(minute: pd.DataFrame) -> pd.DataFrame:
    tr = im.daily_trades(minute)
    tr = tr.assign(net=tr["gross"] - 2 * COST)  # same bp cost model as the others
    a = tr["r_first"].abs()
    thresh = a.shift(1).rolling(IMHV_WINDOW, min_periods=IMHV_WINDOW).quantile(IMHV_QUANTILE)
    active = a > thresh
    return pd.DataFrame({"y": tr["net"].where(active), "x": np.nan, "active": active},
                        index=tr.index).dropna(subset=["y"])


def load_daily(path: str) -> pd.DataFrame:
    d = pd.read_csv(path, index_col=0)
    d.index = pd.to_datetime(d.index, utc=True).tz_convert(None).normalize()
    d.columns = [c.lower() for c in d.columns]
    d = d[["open", "high", "low", "close"]].astype(float).dropna()
    bad = (d <= 0).any(axis=1) | (d["high"] < d["low"])
    if bad.mean() > 0.001:
        raise ValueError(f"{path}: {bad.sum()} malformed daily rows")
    return d[~bad].sort_index()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--daily-dir", required=True, help="dir with <TICKER>.csv daily bars")
    ap.add_argument("--intraday-dir", help="dir with <TICKER>.csv 1m bars (for H4)")
    ap.add_argument("--out", default="edges")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    frames: dict[str, dict[str, pd.DataFrame]] = {h: {} for h in (*DAILY, "IMHV")}
    for tk in TICKERS:
        d = load_daily(os.path.join(a.daily_dir, f"{tk}.csv"))
        for h, fn in DAILY.items():
            f = fn(d)
            frames[h][tk] = f[f.index >= pd.Timestamp(POST_PUB[h])]
        if a.intraday_dir:
            m = bt.load_csv(os.path.join(a.intraday_dir, f"{tk}.csv"))
            f = imhv(m)
            f.index = f.index.tz_localize(None)
            frames["IMHV"][tk] = f[f.index >= pd.Timestamp(POST_PUB["IMHV"])]
    hyps = [h for h in frames if frames[h]]

    rows = []
    for h in hyps:
        for tk in TICKERS:
            f = frames[h][tk]
            b, t, n = effect(f)
            rows.append({"hyp": h, "ticker": tk, "from": f"{f.index[0]:%Y-%m-%d}",
                         "obs": n, "active_days": int(pd.Series(f["active"]).sum()),
                         "effect_bp": b * 1e4, "t": t, "p_one_sided": p_one(t)})
    res = pd.DataFrame(rows)
    res.to_csv(os.path.join(a.out, "all_results.csv"), index=False)

    # Holm on the primary ticker
    prim = res[res["ticker"] == PRIMARY].sort_values("p_one_sided").reset_index(drop=True)
    m = len(prim)
    rejected = set()
    for i, r in prim.iterrows():
        if r["effect_bp"] > 0 and r["p_one_sided"] < FAMILY_ALPHA / (m - i):
            rejected.add(r["hyp"])
        else:
            break

    verdict_rows = []
    for h in hyps:
        others = [tk for tk in TICKERS if tk != PRIMARY]
        pooled = pd.concat({tk: frames[h][tk]["y"] for tk in others}, axis=1)
        if not frames[h][others[0]]["x"].isna().all():
            # dummy regressions: pool the per-ticker effects by averaging the
            # per-day contrast (active-day value minus that ticker's inactive mean)
            parts = []
            for tk in others:
                f = frames[h][tk]
                base = f.loc[f["x"] == 0, "y"].mean()
                parts.append((f["y"] - base).where(f["x"] == 1))
            pooled = pd.concat(parts, axis=1)
        series = pooled.mean(axis=1).dropna()
        _, tp, _ = nw_t(series.to_numpy())
        n_pos = int((res[(res["hyp"] == h) & (res["ticker"] != PRIMARY)]["effect_bp"] > 0).sum())
        confirm = series.mean() > 0 and p_one(tp) < CONFIRM_ALPHA and n_pos >= 2
        spy = prim[prim["hyp"] == h].iloc[0]
        verdict_rows.append({
            "hyp": h, "SPY_effect_bp": spy["effect_bp"], "SPY_t": spy["t"],
            "SPY_p": spy["p_one_sided"], "SPY_holm_reject": h in rejected,
            "others_pooled_t": tp, "others_positive": f"{n_pos}/3",
            "others_confirm": confirm, "EDGE": (h in rejected) and confirm})
    vt = pd.DataFrame(verdict_rows)
    vt.to_csv(os.path.join(a.out, "verdicts.csv"), index=False)
    edges = vt.loc[vt["EDGE"], "hyp"].tolist()
    text = "\n".join([
        "All results (post-publication periods; effect in bp per active day):",
        res.to_string(index=False, float_format="%.3f"), "",
        f"Verdicts (Holm across {m} hypotheses on {PRIMARY}, then cross-ETF confirmation):",
        vt.to_string(index=False, float_format="%.3f"), "",
        f"EDGES: {', '.join(edges)}" if edges else "EDGES: none"])
    print(text)
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("# Pre-registered anomaly family test\n\n```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
