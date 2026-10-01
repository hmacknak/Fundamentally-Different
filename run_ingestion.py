#!/usr/bin/env python3
"""Fetch live prices/macro/fundamentals and load them into the database.

Prices and macro need only outbound network access — yfinance and FRED's
free public CSV export, no account required. Fundamentals need
FMP_API_KEY (paid, ~US$20-30/mo — see docs/DATA_ARCHITECTURE.md and
docs/DECISIONS.md); set it as an environment variable / GitHub Actions
secret, never in code. Without it, fundamentals ingestion is skipped with
a warning rather than failing the whole run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import data_adapters
from service.config import AppConfig, load_dotenv
from service.db import get_session_factory, init_db
from service.db.models import MacroObservation, PricesDaily
from service.ingestion import (
    compute_incremental_start,
    ingest_fundamentals,
    ingest_macro,
    ingest_prices,
    prune_ingestion_runs,
)
from service.universe import load_universe


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe-file")
    ap.add_argument("--start", default="2015-01-01",
                    help="Backfill floor used as a fallback for tickers/series with no "
                         "existing data, and as the literal start date when --full-backfill "
                         "is set. Ordinary scheduled runs ignore this for coverage already in "
                         "the database — see --full-backfill.")
    ap.add_argument("--full-backfill", action="store_true",
                    help="Force --start for prices and macro, ignoring what's already in the "
                         "database. For a deliberate one-time backfill or recovery only — the "
                         "scheduled run must not use this, since it re-fetches and re-upserts "
                         "the full universe's history on every call.")
    ap.add_argument("--skip-fundamentals", action="store_true",
                    help="Fetch prices/macro only; skip the paid FMP call")
    ap.add_argument("--fundamentals-period", default="quarter", choices=["quarter", "annual"],
                    help="Some FMP plan tiers only entitle annual-frequency fundamentals; "
                         "switch to 'annual' if quarterly requests get HTTP 402")
    args = ap.parse_args(argv)

    config = AppConfig.from_env()
    engine = init_db(config.database_url)
    session_factory = get_session_factory(engine)
    universe = load_universe(args.universe_file)
    end = str(dt.date.today())

    default_start = dt.date.fromisoformat(args.start)
    fundamentals_failed = False
    with session_factory() as session:
        pruned = prune_ingestion_runs(session)
        if pruned:
            print(f"[maintenance] pruned {pruned} old data_ingestion_runs row(s)")

        if args.full_backfill:
            prices_start = macro_start = default_start
        else:
            prices_start = compute_incremental_start(session, PricesDaily.date,
                                                      PricesDaily.ticker, universe, default_start)
            macro_start = compute_incremental_start(session, MacroObservation.observation_date,
                                                     MacroObservation.series_name,
                                                     data_adapters.ALL_MACRO_SERIES, default_start)

        prices = data_adapters.build_prices_csv(universe, start=str(prices_start), end=end,
                                                out_path="/tmp/_prices_ingest.csv")
        r_prices = ingest_prices(session, prices, provider="yfinance")
        print(f"[prices] {r_prices.status}: {r_prices.rows_ingested} rows "
             f"(start={prices_start})")

        macro = data_adapters.build_macro_csv(start=str(macro_start), end=end,
                                              out_path="/tmp/_macro_ingest.csv")
        r_macro = ingest_macro(session, macro, provider="fred+yfinance")
        print(f"[macro] {r_macro.status}: {r_macro.rows_ingested} rows (start={macro_start})")

        if args.skip_fundamentals:
            print("[fundamentals] skipped (--skip-fundamentals)")
        elif not config.fmp_api_key:
            print("[fundamentals] skipped: FMP_API_KEY not set. This is a paid provider "
                 "(~US$20-30/mo) that needs an account — see docs/DECISIONS.md for how "
                 "to enable it once you're ready.", file=sys.stderr)
        else:
            # Fetched separately from prices/macro so a provider outage or plan/key
            # problem on FMP's side doesn't discard prices/macro data already
            # committed above, or hide behind an unrelated traceback.
            #
            # No incremental --start here: build_fundamentals_csv always pulls the
            # last `limit` periods per ticker from FMP regardless of DB state, so
            # its fetch size is already bounded; only the no-op upsert guard in
            # ingest_fundamentals applies to this domain.
            try:
                fundamentals = data_adapters.build_fundamentals_csv(
                    universe, api_key=config.fmp_api_key, out_path="/tmp/_fundamentals_ingest.csv",
                    period=args.fundamentals_period)
                r_fund = ingest_fundamentals(session, fundamentals, provider="fmp")
                print(f"[fundamentals] {r_fund.status}: {r_fund.rows_ingested} rows")
            except Exception as e:
                print(f"[fundamentals] failed: {e}", file=sys.stderr)
                fundamentals_failed = True

    return 1 if fundamentals_failed else 0


if __name__ == "__main__":
    sys.exit(main())
