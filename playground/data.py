"""Load daily prices for playground experiments from the already-ingested
database -- no new fetching, no new provider. Reuses the same DATABASE_URL
the production pipeline uses (service/config.py, service/db/session.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from service.config import AppConfig  # noqa: E402
from service.db.models import PricesDaily  # noqa: E402
from service.db.session import get_engine, get_session_factory  # noqa: E402


def load_daily_prices(ticker: str, start: str | None = None, end: str | None = None) -> pd.Series:
    """Adjusted close, date-indexed, ascending, for one ticker."""
    config = AppConfig.from_env()
    engine = get_engine(config.database_url)
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        query = session.query(PricesDaily.date, PricesDaily.adj_close).filter(
            PricesDaily.ticker == ticker.upper())
        if start:
            query = query.filter(PricesDaily.date >= pd.Timestamp(start).date())
        if end:
            query = query.filter(PricesDaily.date <= pd.Timestamp(end).date())
        rows = query.order_by(PricesDaily.date).all()
    if not rows:
        raise RuntimeError(
            f"No price history found in the database for {ticker!r}. Run the "
            f"production ingestion pipeline first (run_ingestion.py) -- the "
            f"playground reads the same table, it doesn't fetch its own data.")
    dates, closes = zip(*rows)
    return pd.Series(closes, index=pd.to_datetime(dates), name=ticker.upper())
