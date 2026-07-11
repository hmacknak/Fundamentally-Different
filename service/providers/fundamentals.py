"""Quarterly fundamentals via FMP (paid, ~US$20-30/mo — the point-in-time
critical, and only non-free, feed this project uses).

Mapping is a pure function so it is unit-testable with canned key-metrics
and ratios JSON — no network access, and no API key, needed in CI.

data_adapters.py calls FMP's "stable" endpoints (migrated from legacy
/api/v3 — see docs/DECISIONS.md). Field names below (freeCashFlowYield,
debtToEquity, etc.) were carried over from the legacy response shape;
they were not independently re-verified against a live "stable" response,
so if a real ingestion run comes back with a field unexpectedly all-None,
check that field's name first against FMP's current docs before assuming
something else is wrong — missing/renamed fields degrade to None here
rather than crash, by design.

`shares_dilution` is intentionally left unset: FMP's key-metrics/ratios
endpoints used here don't carry a shares-outstanding history, so there is
nothing honest to derive it from (CLAUDE.md rule: never fabricate a data
field). Wiring a real shares-outstanding feed is a documented follow-up.
"""
from __future__ import annotations

import pandas as pd

FUNDAMENTALS_COLUMNS = [
    "date", "ticker", "fcf_yield", "debt_to_equity", "roe", "revenue_growth",
    "pe", "ev_ebitda", "dividend_yield", "interest_coverage", "gross_margin",
    "operating_margin", "free_cash_flow_margin", "eps_revision", "shares_dilution",
]


def map_fmp_period_to_fundamentals_row(ticker: str, key_metric: dict, ratio: dict) -> dict:
    """Map one FMP key-metrics record (+ matching ratios record) to the engine's
    fundamentals.csv schema for a single (ticker, period) observation."""
    return {
        "date": key_metric["date"],
        "ticker": ticker,
        "fcf_yield": key_metric.get("freeCashFlowYield"),
        "debt_to_equity": key_metric.get("debtToEquity"),
        "roe": key_metric.get("roe"),
        "pe": key_metric.get("peRatio"),
        "ev_ebitda": key_metric.get("enterpriseValueOverEBITDA"),
        "dividend_yield": key_metric.get("dividendYield"),
        "interest_coverage": ratio.get("interestCoverage"),
        "gross_margin": ratio.get("grossProfitMargin"),
        "operating_margin": ratio.get("operatingProfitMargin"),
        "free_cash_flow_margin": None,
        "eps_revision": None,  # needs an estimates feed, not available from key-metrics/ratios
        "shares_dilution": None,  # no shares-outstanding history in these endpoints
        "_revenue_per_share": key_metric.get("revenuePerShare"),
    }


def compute_revenue_growth_yoy_per_share(df: pd.DataFrame) -> pd.DataFrame:
    """Derive quarterly YoY revenue-per-share growth, then drop the working column."""
    df = df.sort_values(["ticker", "date"]).copy()
    df["revenue_growth"] = df.groupby("ticker")["_revenue_per_share"].pct_change(4)
    return df.drop(columns=[c for c in df.columns if c.startswith("_")])
