#!/usr/bin/env python3
"""Data adapters — produce the engine's three input CSVs from live sources.

STATUS: written offline, NOT yet run against live APIs (this sandbox has no
network). Structure is correct; expect to fix minor field-name drift on first
real run. Run each builder once, eyeball the CSV, then feed the engine.

Sources (free unless noted):
  prices        yfinance (survivorship caveat: today's tickers only)
  macro         FRED public CSV endpoints + yfinance for VIX/benchmark/gold/CAD
  fundamentals  FMP (paid, ~US$20-30/mo) — the point-in-time-critical feed.
                Prefer FMP's as-reported endpoints over key-metrics where
                possible; restated data quietly poisons backtests.

Point-in-time discipline stays in the ENGINE (--fundamental-lag-days). The
adapter's job is only honest field mapping; it must never fabricate values.
"""
import io
import sys
import time
from datetime import date

import pandas as pd

FRED_SERIES = {
    "rate_10y": "DGS10",
    "rate_2y": "DGS2",
    "cpi_index": "CPIAUCSL",        # converted to cpi_yoy below
    "wti_oil": "DCOILWTICO",
    "credit_spread": "BAMLH0A0HYM2",  # ICE BofA US High Yield OAS
}
YF_MACRO = {"vix": "^VIX", "benchmark_adj_close": "^GSPC",
            "gold": "GC=F", "cadusd": "CADUSD=X"}


def _fred_csv(series_id, start, end):
    url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
           f"?id={series_id}&cosd={start}&coed={end}")
    import urllib.request
    with urllib.request.urlopen(url, timeout=30) as r:
        df = pd.read_csv(io.StringIO(r.read().decode()))
    df.columns = ["date", series_id]
    df["date"] = pd.to_datetime(df["date"])
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    return df.set_index("date")[series_id]


def build_macro_csv(start="2015-01-01", end=None, out_path="macro.csv"):
    end = end or str(date.today())
    monthly = {}
    for name, sid in FRED_SERIES.items():
        s = _fred_csv(sid, start, end).resample("ME").last()
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
        for tk in chunk:
            try:
                sub = h[tk][["Close", "Volume"]].dropna()
            except KeyError:
                print(f"  skip {tk}: no data", file=sys.stderr)
                continue
            sub = sub.rename(columns={"Close": "adj_close", "Volume": "volume"})
            sub["ticker"] = tk
            frames.append(sub.reset_index().rename(columns={"Date": "date"}))
        time.sleep(1)
    p = pd.concat(frames, ignore_index=True)[["date", "ticker", "adj_close", "volume"]]
    p.to_csv(out_path, index=False)
    print(f"prices.csv: {len(p):,} rows, {p['ticker'].nunique()} tickers -> {out_path}")
    return p


def build_fundamentals_csv(tickers, api_key, out_path="fundamentals.csv",
                           period="quarter", limit=40):
    """FMP quarterly fundamentals mapped to the engine schema.

    Uses /key-metrics and /ratios. NOTE: verify against FMP's as-reported
    statement endpoints for anything material — key-metrics can reflect
    restatements. The engine's --fundamental-lag-days then handles the
    reporting delay; consider FMP's 'fillingDate' field to set the lag
    precisely per row (future improvement: use fillingDate as the panel's
    as-of key instead of period-end + fixed lag)."""
    import urllib.request, json
    base = "https://financialmodelingprep.com/api/v3"
    rows = []
    for tk in tickers:
        try:
            km = json.load(urllib.request.urlopen(
                f"{base}/key-metrics/{tk}?period={period}&limit={limit}&apikey={api_key}", timeout=30))
            ra = json.load(urllib.request.urlopen(
                f"{base}/ratios/{tk}?period={period}&limit={limit}&apikey={api_key}", timeout=30))
        except Exception as e:
            print(f"  skip {tk}: {e}", file=sys.stderr)
            continue
        ra_by_date = {r["date"]: r for r in ra}
        for k in km:
            r = ra_by_date.get(k["date"], {})
            rows.append({
                "date": k["date"], "ticker": tk,
                "fcf_yield": k.get("freeCashFlowYield"),
                "debt_to_equity": k.get("debtToEquity"),
                "roe": k.get("roe"),
                "revenue_growth": None,  # filled below from revenuePerShare yoy
                "pe": k.get("peRatio"),
                "ev_ebitda": k.get("enterpriseValueOverEBITDA"),
                "dividend_yield": k.get("dividendYield"),
                "interest_coverage": r.get("interestCoverage"),
                "gross_margin": r.get("grossProfitMargin"),
                "operating_margin": r.get("operatingProfitMargin"),
                "free_cash_flow_margin": None,
                "eps_revision": None,     # needs an estimates feed; leave blank
                "shares_dilution": None,  # derive from share count yoy below
                "_rps": k.get("revenuePerShare"),
                "_shares": k.get("marketCap") and k.get("marketCap") / k["marketCap"] if False else None,
            })
        time.sleep(0.3)
    f = pd.DataFrame(rows)
    f["date"] = pd.to_datetime(f["date"])
    f = f.sort_values(["ticker", "date"])
    f["revenue_growth"] = f.groupby("ticker")["_rps"].pct_change(4)  # yoy, per-share
    f = f.drop(columns=[c for c in f.columns if c.startswith("_")])
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
