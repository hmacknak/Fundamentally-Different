"""Default MVP universe: a static, documented U.S. large-cap list.

Per docs/PRD.md ("Universe: configurable U.S. large-cap list, initially
50-100 names") and CLAUDE.md rule 7 (the owner must not need to edit
configuration), this ships with a sensible default so the system runs out
of the box. A developer (not the non-technical owner) can point
load_universe() at a different file to change coverage without touching
engine code.

SURVIVORSHIP WARNING (see README.md / data_adapters.py): this reflects
today's constituents only. Reconstructing historical membership is a
documented Phase 2 item, not addressed here.
"""
from __future__ import annotations

DEFAULT_UNIVERSE = [
    # Technology
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "ADBE", "CRM",
    "INTC", "AMD", "QCOM", "TXN", "IBM", "CSCO",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "SPGI", "V", "MA",
    # Healthcare
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
    # Consumer
    "WMT", "PG", "KO", "PEP", "COST", "HD", "MCD", "NKE", "DIS", "SBUX",
    # Industrials / Energy
    "XOM", "CVX", "CAT", "BA", "HON", "GE", "UPS", "LMT", "RTX", "UNP",
    # Communication
    "NFLX", "CMCSA", "T", "VZ",
]


def load_universe(path: str | None = None) -> list[str]:
    """Load tickers from `path` (one per line, '#' comments allowed), or the
    built-in default when no path is given."""
    if not path:
        return list(DEFAULT_UNIVERSE)
    with open(path) as fh:
        return [line.strip().upper() for line in fh
                if line.strip() and not line.strip().startswith("#")]
