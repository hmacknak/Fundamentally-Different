#!/usr/bin/env python3
"""Download full-history daily bars (dividend- and split-adjusted OHLC)
from Yahoo via yfinance, with provenance. Fails loudly on empty data."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def main(argv=None) -> int:
    import yfinance as yf

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    prov = {}
    for tk in a.tickers:
        retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
        df = yf.download(tk, period="max", interval="1d", auto_adjust=True,
                         progress=False, threads=False)
        if df is None or df.empty:
            print(f"error: Yahoo returned no daily bars for {tk}", file=sys.stderr)
            return 1
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        df.to_csv(os.path.join(a.out, f"{tk}.csv"))
        prov[tk] = {"source": "Yahoo Finance via yfinance, 1d, auto_adjust=True",
                    "retrieved_utc": retrieved, "first": str(df.index.min()),
                    "last": str(df.index.max()), "rows": len(df)}
        print(tk, prov[tk])
    with open(os.path.join(a.out, "provenance.json"), "w") as f:
        json.dump(prov, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
