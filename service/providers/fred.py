"""FRED macro series — public CSV export, no API key required.

Uses FRED's public `fredgraph.csv` endpoint rather than the official
`fredapi` package (which needs a free FRED account/key). This keeps macro
ingestion account-free for the MVP; switching to the official API later
is a documented, one-file change (see docs/DECISIONS.md).

Parsing is a pure function so it is unit-testable with a canned CSV string
— no network access needed in CI.
"""
from __future__ import annotations

import io
import urllib.request
from collections.abc import Callable

import pandas as pd

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def parse_fred_csv(raw_text: str, series_id: str) -> pd.Series:
    """Parse FRED's public CSV export into a date-indexed numeric series."""
    df = pd.read_csv(io.StringIO(raw_text))
    df.columns = ["date", series_id]
    df["date"] = pd.to_datetime(df["date"])
    df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
    return df.set_index("date")[series_id]


def _default_http_get(url: str, timeout: int) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode()


def fetch_fred_series(series_id: str, start: str, end: str, timeout: int = 30,
                       http_get: Callable[[str, int], str] = _default_http_get) -> pd.Series:
    """Fetch and parse one FRED series. Inject `http_get` in tests to avoid the network."""
    url = f"{FRED_CSV_URL}?id={series_id}&cosd={start}&coed={end}"
    raw_text = http_get(url, timeout)
    return parse_fred_csv(raw_text, series_id)
