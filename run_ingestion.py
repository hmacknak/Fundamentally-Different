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
from service.ingestion import ingest_fundamentals, ingest_macro, ingest_prices
from service.universe import load_universe


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe-file")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--skip-fundamentals", action="store_true",
                    help="Fetch prices/macro only; skip the paid FMP call")
    args = ap.parse_args(argv)

    config = AppConfig.from_env()
    engine = init_db(config.database_url)
    session_factory = get_session_factory(engine)
    universe = load_universe(args.universe_file)
    end = str(dt.date.today())

    fundamentals_failed = False
    with session_factory() as session:
        prices = data_adapters.build_prices_csv(universe, start=args.start, end=end,
                                                out_path="/tmp/_prices_ingest.csv")
        r_prices = ingest_prices(session, prices, provider="yfinance")
        print(f"[prices] {r_prices.status}: {r_prices.rows_ingested} rows")

        macro = data_adapters.build_macro_csv(start=args.start, end=end,
                                              out_path="/tmp/_macro_ingest.csv")
        r_macro = ingest_macro(session, macro, provider="fred+yfinance")
        print(f"[macro] {r_macro.status}: {r_macro.rows_ingested} rows")

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
            try:
                fundamentals = data_adapters.build_fundamentals_csv(
                    universe, api_key=config.fmp_api_key, out_path="/tmp/_fundamentals_ingest.csv")
                r_fund = ingest_fundamentals(session, fundamentals, provider="fmp")
                print(f"[fundamentals] {r_fund.status}: {r_fund.rows_ingested} rows")
            except Exception as e:
                print(f"[fundamentals] failed: {e}", file=sys.stderr)
                fundamentals_failed = True

    return 1 if fundamentals_failed else 0


if __name__ == "__main__":
    sys.exit(main())
