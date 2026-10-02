#!/usr/bin/env python3
"""Descriptive comparison: relative-IBS sector portfolio vs SPY buy-and-hold.

Portfolio: each day, equal weight across the sector SPDRs whose relative-IBS
signal fired at the prior close (rel_ibs.py rule, close-based, 2 bp per side);
cash at 0% otherwise. SPY: buy and hold, adjusted close. Sharpe uses rf = 0.
Periods: 1999-2013 (the confirmed sample) and 2014+ (close-based; NOT the
executable 15:50 version, which still needs a clean rerun).
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge_family as ef
import rel_ibs as ri

PERIODS = {"1999-2013": ("1999-01-01", "2013-12-31"), "2014-2026": ("2014-01-01", None)}


def portfolio_returns(daily: dict[str, pd.DataFrame], mkt: pd.DataFrame) -> pd.Series:
    m_ibs = ri.ibs(mkt)
    legs = []
    for tk in ri.SECTORS:
        d = daily[tk]
        sig = ((ri.ibs(d) < ri.IBS_LOW) & (m_ibs.reindex(d.index) >= ri.IBS_LOW)).shift(
            1, fill_value=False)
        r = d["close"].pct_change() - 2 * ri.COST_BP / 1e4
        legs.append(r.where(sig).rename(tk))
    return pd.concat(legs, axis=1).mean(axis=1).fillna(0.0)


def metrics(r: pd.Series) -> dict:
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    sd = r.std(ddof=1)
    return {"total_%": (eq.iloc[-1] - 1) * 100,
            "CAGR_%": (eq.iloc[-1] ** (1 / yrs) - 1) * 100,
            "vol_%": sd * math.sqrt(252) * 100,
            "Sharpe": r.mean() / sd * math.sqrt(252) if sd > 0 else np.nan,
            "maxDD_%": (eq / eq.cummax() - 1).min() * 100,
            "in_mkt_%": (r != 0).mean() * 100,
            "worst_day_%": r.min() * 100}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--daily-dir", required=True)
    ap.add_argument("--out", default="compare_spy")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    daily = {tk: ef.load_daily(os.path.join(a.daily_dir, f"{tk}.csv"))
             for tk in (*ri.SECTORS, "SPY")}
    port = portfolio_returns(daily, daily["SPY"])
    spy = daily["SPY"]["close"].pct_change()
    rows = []
    for name, (s, e) in PERIODS.items():
        sel = lambda x: x[(x.index >= pd.Timestamp(s)) &  # noqa: E731
                          ((x.index <= pd.Timestamp(e)) if e else True)]
        p, b = sel(port), sel(spy).dropna()
        p = p.reindex(b.index).fillna(0.0)
        rows.append({"period": name, "strategy": "Relative IBS", **metrics(p)})
        rows.append({"period": name, "strategy": "SPY buy & hold", **metrics(b)})
        corr = p[p != 0].corr(b[p != 0])
        rows.append({"period": name, "strategy": f"(corr on active days {corr:.2f})"})
    t = pd.DataFrame(rows)
    text = t.to_string(index=False, float_format="%.2f", na_rep="")
    print(text)
    t.to_csv(os.path.join(a.out, "compare.csv"), index=False)
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("# Relative IBS vs SPY buy-and-hold\n\n```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
