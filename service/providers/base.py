"""Provider interfaces.

Per docs/DATA_ARCHITECTURE.md's provider strategy: the research engine
consumes prices.csv / fundamentals.csv / macro.csv schemas regardless of
which vendor supplied the data, so a provider can be swapped later without
touching amp/. Each concrete provider module below separates the network
call (untestable without live credentials) from the schema-mapping logic
(pure functions, unit tested with canned responses — no network access in
CI).
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd


class PriceProvider(Protocol):
    def fetch_prices(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        """Return columns: date, ticker, adj_close, volume."""
        ...


class MacroProvider(Protocol):
    def fetch_macro(self, start: str, end: str) -> pd.DataFrame:
        """Return columns: date (monthly) plus macro series per the engine's macro.csv schema."""
        ...


class FundamentalsProvider(Protocol):
    def fetch_fundamentals(self, tickers: list[str]) -> pd.DataFrame:
        """Return columns matching amp.validation.REQUIRED['fundamentals'] plus OPTIONAL_FUND."""
        ...
