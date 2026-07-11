"""Daily prices via yfinance.

SURVIVORSHIP WARNING (carried over from data_adapters.py): yfinance serves
today's listings. Reconstruct historical index membership before trusting
multi-year factor statistics (tracked as a Phase 2 item in the roadmap).

The yfinance network call and the schema-mapping logic are kept separate so
the mapping can be unit tested with a fabricated DataFrame shaped like
yfinance's `group_by="ticker"` output — no network access in CI.
"""
from __future__ import annotations

import pandas as pd

PRICE_COLUMNS = ["date", "ticker", "adj_close", "volume"]


def map_yfinance_chunk_to_prices_schema(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Map one yfinance `group_by="ticker"` download to the engine's prices.csv schema."""
    frames = []
    for tk in tickers:
        try:
            sub = raw[tk][["Close", "Volume"]].dropna()
        except KeyError:
            continue
        sub = sub.rename(columns={"Close": "adj_close", "Volume": "volume"})
        sub["ticker"] = tk
        frames.append(sub.reset_index().rename(columns={"Date": "date"}))
    if not frames:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    return pd.concat(frames, ignore_index=True)[PRICE_COLUMNS]
