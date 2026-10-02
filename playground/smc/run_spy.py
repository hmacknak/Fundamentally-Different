#!/usr/bin/env python3
"""Download SPY 1-minute bars from Yahoo (yfinance) and run the BOS/CHoCH
retest backtest on 1/5/15/30/60-minute bars, plus a detailed 1m report.

Yahoo only serves about the last 30 days of 1-minute bars, so a run on this
data is a smoke test (a few dozen trades), not evidence of an edge.

Examples:
  python playground/smc/run_spy.py
  python playground/smc/run_spy.py --csv my_longer_export.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest_smc as bt


def download_yahoo_1m(ticker: str, days: int = 29) -> pd.DataFrame:
    """Fetch 1m bars in 7-day chunks (Yahoo's per-request limit for 1m)."""
    import yfinance as yf

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    frames = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=7), end)
        df = yf.download(ticker, start=cur, end=nxt, interval="1m", auto_adjust=False,
                         prepost=False, progress=False, threads=False)
        if df is not None and len(df):
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            frames.append(df)
        cur = nxt
    if not frames:
        raise RuntimeError(f"Yahoo returned no 1-minute bars for {ticker}; refusing to "
                           f"continue (no synthetic substitute).")
    out = pd.concat(frames)
    out.columns = [str(c).lower() for c in out.columns]
    out = out[["open", "high", "low", "close", "volume"]]
    out.index.name = "timestamp"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="use this 1m CSV instead of downloading")
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--save", default="spy_1min.csv")
    ap.add_argument("--compare", default="1,5,15,30,60")
    ap.add_argument("--out", default="results")
    ap.add_argument("--plot-trades", type=int, default=10)
    a = ap.parse_args(argv)

    os.makedirs(a.out, exist_ok=True)
    if a.csv:
        csv_path = a.csv
    else:
        retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw = download_yahoo_1m(a.ticker)
        raw.to_csv(a.save)
        csv_path = a.save
        meta = {"ticker": a.ticker, "source": "Yahoo Finance via yfinance, interval=1m, "
                "auto_adjust=False, prepost=False", "retrieved_utc": retrieved,
                "first_bar": str(raw.index.min()), "last_bar": str(raw.index.max()),
                "rows": len(raw)}
        with open(os.path.join(a.out, "data_provenance.json"), "w") as f:
            json.dump(meta, f, indent=2)
        print(f"saved {len(raw)} bars to {a.save} ({meta['first_bar']} .. {meta['last_bar']})")

    rc = bt.main([csv_path, "--compare", a.compare, "--out", os.path.join(a.out, "compare")])
    if rc:
        return rc
    return bt.main([csv_path, "--timeframe", "1", "--out", os.path.join(a.out, "1m"),
                    "--plot-trades", str(a.plot_trades)])


if __name__ == "__main__":
    sys.exit(main())
