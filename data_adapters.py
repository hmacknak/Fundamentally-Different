#!/usr/bin/env python3
"""Data adapters — produce the engine's three input CSVs from live sources.

STATUS: written offline, NOT yet run against live APIs (this sandbox has no
network). Structure is correct; expect to fix minor field-name drift on first
real run. Run each builder once, eyeball the CSV, then feed the engine.

Sources (free unless noted):
  prices        yfinance (survivorship caveat: today's tickers only)
  macro         FRED public CSV endpoint (no API key) + yfinance for
                VIX/benchmark/gold/CAD
  fundamentals  FMP (paid, ~US$20-30/mo) — the point-in-time-critical feed.
                Prefer FMP's as-reported endpoints over key-metrics where
                possible; restated data quietly poisons backtests.

Point-in-time discipline stays in the ENGINE (--fundamental-lag-days). The
adapter's job is only honest field mapping; it must never fabricate values.

Schema-mapping logic lives in service/providers/ as pure, unit-tested
functions; this module wires them to the live network calls.
"""
import sys
import time
from datetime import date

import pandas as pd

from service.providers.fred import fetch_fred_series
from service.providers.fundamentals import (
    compute_revenue_growth_yoy_per_share,
    map_fmp_period_to_fundamentals_row,
)
from service.providers.prices import map_yfinance_chunk_to_prices_schema

FRED_SERIES = {
    "rate_10y": "DGS10",
    "rate_2y": "DGS2",
    "cpi_index": "CPIAUCSL",        # converted to cpi_yoy below
    "wti_oil": "DCOILWTICO",
    "credit_spread": "BAMLH0A0HYM2",  # ICE BofA US High Yield OAS
}
YF_MACRO = {"vix": "^VIX", "benchmark_adj_close": "^GSPC",
            "gold": "GC=F", "cadusd": "CADUSD=X"}


def build_macro_csv(start="2015-01-01", end=None, out_path="macro.csv"):
    end = end or str(date.today())
    monthly = {}
    for name, sid in FRED_SERIES.items():
        s = fetch_fred_series(sid, start, end).resample("ME").last()
        monthly[name] = s
        time.sleep(0.5)
    import yfinance as yf
    for name, tk in YF_MACRO.items():
        h = yf.download(tk, start=start, end=end, progress=False, auto_adjust=True)
        monthly[name] = h["Close"].resample("ME").last().squeeze()
    m = pd.DataFrame(monthly)
    m["cpi_yoy"] = m["cpi_index"].pct_change(12) * 100
    m = m.drop(columns=["cpi_index"]).dropna(how="all").reset_index()
    m = m.rename(columns={"index": "date", "Date": "date"})
    m.to_csv(out_path, index=False)
    print(f"macro.csv: {len(m)} rows -> {out_path}")
    return m


def build_prices_csv(tickers, start="2015-01-01", end=None, out_path="prices.csv"):
    """SURVIVORSHIP WARNING: passing today's index members backtests only the
    survivors. For S&P 500, reconstruct historical membership from the public
    change log (Wikipedia 'List of S&P 500 companies' + its change table)
    before trusting multi-year factor stats."""
    end = end or str(date.today())
    import yfinance as yf
    frames = []
    for i in range(0, len(tickers), 50):
        chunk = tickers[i:i + 50]
        h = yf.download(chunk, start=start, end=end, progress=False,
                        auto_adjust=True, group_by="ticker")
        mapped = map_yfinance_chunk_to_prices_schema(h, chunk)
        missing = set(chunk) - set(mapped["ticker"].unique())
        for tk in missing:
            print(f"  skip {tk}: no data", file=sys.stderr)
        frames.append(mapped)
        time.sleep(1)
    p = pd.concat(frames, ignore_index=True)
    p.to_csv(out_path, index=False)
    print(f"prices.csv: {len(p):,} rows, {p['ticker'].nunique()} tickers -> {out_path}")
    return p


def build_fundamentals_csv(tickers, api_key, out_path="fundamentals.csv",
                           period="quarter", limit=40):
    """FMP quarterly fundamentals mapped to the engine schema.

    Uses FMP's "stable" /key-metrics and /ratios endpoints (ticker passed as
    a query parameter, e.g. /stable/key-metrics?symbol=AAPL). The older
    /api/v3/key-metrics/{ticker} path-parameter form is legacy and returns
    403 for accounts created after FMP's August 2025 cutover — caught on a
    live run against a real (post-cutover) FMP account.

    NOTE: verify against FMP's as-reported statement endpoints for anything
    material — key-metrics can reflect restatements. The engine's
    --fundamental-lag-days then handles the reporting delay; consider FMP's
    'fillingDate' field to set the lag precisely per row (future
    improvement: use fillingDate as the panel's as-of key instead of
    period-end + fixed lag)."""
    import json
    import urllib.request
    base = "https://financialmodelingprep.com/stable"
    rows = []
    errors = []
    for tk in tickers:
        try:
            km = json.load(urllib.request.urlopen(
                f"{base}/key-metrics?symbol={tk}&period={period}&limit={limit}&apikey={api_key}",
                timeout=30))
            ra = json.load(urllib.request.urlopen(
                f"{base}/ratios?symbol={tk}&period={period}&limit={limit}&apikey={api_key}",
                timeout=30))
        except Exception as e:
            print(f"  skip {tk}: {e}", file=sys.stderr)
            errors.append(str(e))
            continue
        ra_by_date = {r["date"]: r for r in ra}
        for k in km:
            rows.append(map_fmp_period_to_fundamentals_row(tk, k, ra_by_date.get(k["date"], {})))
        time.sleep(0.3)
    if not rows:
        sample = errors[0] if errors else "no tickers requested"
        raise RuntimeError(
            f"FMP returned no usable data for any of {len(tickers)} ticker(s) "
            f"(sample error: {sample}). Check that FMP_API_KEY is valid and that your "
            f"FMP plan includes the key-metrics and ratios endpoints — a 403 typically "
            f"means the key or plan doesn't have access to these endpoints."
        )
    f = pd.DataFrame(rows)
    f["date"] = pd.to_datetime(f["date"])
    f = compute_revenue_growth_yoy_per_share(f)
    f.to_csv(out_path, index=False)
    print(f"fundamentals.csv: {len(f):,} rows -> {out_path}")
    return f


if __name__ == "__main__":
    print(__doc__)
    print("Example:\n"
          "  from data_adapters import *\n"
          "  build_macro_csv('2015-01-01')\n"
          "  build_prices_csv(['AAPL','MSFT',...])\n"
          "  build_fundamentals_csv(['AAPL','MSFT',...], api_key='FMP_KEY')")
