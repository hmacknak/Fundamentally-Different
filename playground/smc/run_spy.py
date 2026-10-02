#!/usr/bin/env python3
"""Download SPY 1-minute bars and run the BOS/CHoCH retest backtest on
1/5/15/30/60-minute bars, plus a detailed 1m report.

Sources:
  alpaca  multi-year history; needs ALPACA_API_KEY and ALPACA_API_SECRET
          in the environment (a free account works).
  yahoo   no key, but only ~30 days of 1m bars, so it's a smoke test only.
  auto    (default) alpaca if both keys are set, otherwise yahoo.

With a multi-year download, the last `--holdout-months` are also reported
separately as an untouched holdout period.

Examples:
  python playground/smc/run_spy.py
  python playground/smc/run_spy.py --source alpaca --years 5
  python playground/smc/run_spy.py --csv my_longer_export.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

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


ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/{ticker}/bars"


def download_alpaca_1m(ticker: str, years: float, key: str, secret: str,
                       feed: str = "sip", session: requests.Session | None = None
                       ) -> pd.DataFrame:
    """Fetch raw (unadjusted) 1m bars from Alpaca's market-data API, paging
    through `next_page_token`. Alpaca stamps bars at their start, in UTC.

    The SIP feed (all US venues) is used by default. Free accounts can read
    it for anything older than 15 minutes, so the end is set 20 minutes back.
    """
    http = session or requests.Session()
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    start = end - timedelta(days=round(365.25 * years))
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    params = {"timeframe": "1Min", "start": start.isoformat(timespec="seconds"),
              "end": end.isoformat(timespec="seconds"), "limit": 10000,
              "adjustment": "raw", "feed": feed, "sort": "asc"}
    rows: list[dict] = []
    while True:
        resp = http.get(ALPACA_BARS_URL.format(ticker=ticker), headers=headers,
                        params=params, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Alpaca returned HTTP {resp.status_code}: "
                               f"{resp.text[:300]}")
        body = resp.json()
        rows.extend(body.get("bars") or [])
        token = body.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    if not rows:
        raise RuntimeError(f"Alpaca returned no 1-minute bars for {ticker}; refusing "
                           f"to continue (no synthetic substitute).")
    df = pd.DataFrame(rows).rename(columns={"t": "timestamp", "o": "open", "h": "high",
                                            "l": "low", "c": "close", "v": "volume"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]


def run_period(csv_path: str, compare: str, out: str, start: str | None = None,
               end: str | None = None) -> int:
    args = [csv_path, "--compare", compare, "--out", out]
    if start:
        args += ["--start", start]
    if end:
        args += ["--end", end]
    return bt.main(args)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="use this 1m CSV instead of downloading")
    ap.add_argument("--source", choices=["auto", "alpaca", "yahoo"], default="auto")
    ap.add_argument("--years", type=float, default=5.0, help="Alpaca history length")
    ap.add_argument("--feed", default="sip", help="Alpaca feed: sip (all venues) or iex")
    ap.add_argument("--holdout-months", type=int, default=12)
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--save", default="spy_1min.csv")
    ap.add_argument("--compare", default="1,5,15,30,60")
    ap.add_argument("--out", default="results")
    ap.add_argument("--plot-trades", type=int, default=10)
    ap.add_argument("--download-only", action="store_true",
                    help="save the CSV and provenance, skip the backtests")
    a = ap.parse_args(argv)

    os.makedirs(a.out, exist_ok=True)
    if a.csv:
        csv_path = a.csv
    else:
        key = os.environ.get("ALPACA_API_KEY", "").strip()
        secret = os.environ.get("ALPACA_API_SECRET", "").strip()
        source = a.source
        if source == "auto":
            source = "alpaca" if key and secret else "yahoo"
        if source == "alpaca" and not (key and secret):
            print("error: --source alpaca needs ALPACA_API_KEY and ALPACA_API_SECRET",
                  file=sys.stderr)
            return 2
        retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if source == "alpaca":
            raw = download_alpaca_1m(a.ticker, a.years, key, secret, feed=a.feed)
            desc = (f"Alpaca market data v2, timeframe=1Min, feed={a.feed}, "
                    f"adjustment=raw")
        else:
            raw = download_yahoo_1m(a.ticker)
            desc = "Yahoo Finance via yfinance, interval=1m, auto_adjust=False, prepost=False"
        os.makedirs(os.path.dirname(a.save) or ".", exist_ok=True)
        raw.to_csv(a.save)
        csv_path = a.save
        meta = {"ticker": a.ticker, "source": desc, "retrieved_utc": retrieved,
                "first_bar": str(raw.index.min()), "last_bar": str(raw.index.max()),
                "rows": len(raw)}
        with open(os.path.join(a.out, "data_provenance.json"), "w") as f:
            json.dump(meta, f, indent=2)
        print(f"saved {len(raw)} bars from {source} to {a.save} "
              f"({meta['first_bar']} .. {meta['last_bar']})")

    if a.download_only:
        return 0

    print("\n=== Full period ===")
    rc = run_period(csv_path, a.compare, os.path.join(a.out, "compare"))
    if rc:
        return rc

    first, last = bt.load_csv(csv_path).index[[0, -1]]
    split = (last - pd.DateOffset(months=a.holdout_months)).normalize()
    if a.holdout_months > 0 and split - first >= pd.Timedelta(days=365):
        day = pd.Timedelta(days=1)
        print(f"\n=== In-sample: {first:%Y-%m-%d} .. {split - day:%Y-%m-%d} ===")
        rc = run_period(csv_path, a.compare, os.path.join(a.out, "in_sample"),
                        end=f"{split - day:%Y-%m-%d}")
        if rc:
            return rc
        print(f"\n=== Holdout (last {a.holdout_months} months): "
              f"{split:%Y-%m-%d} .. {last:%Y-%m-%d} ===")
        rc = run_period(csv_path, a.compare, os.path.join(a.out, "holdout"),
                        start=f"{split:%Y-%m-%d}")
        if rc:
            return rc

    print("\n=== 1m detail ===")
    return bt.main([csv_path, "--timeframe", "1", "--out", os.path.join(a.out, "1m"),
                    "--plot-trades", str(a.plot_trades)])


if __name__ == "__main__":
    sys.exit(main())
