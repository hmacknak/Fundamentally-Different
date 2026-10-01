#!/usr/bin/env python3
"""Single entrypoint: "Run the Market Priority Report."

Non-technical usage: trigger the "Run Market Priority Report" GitHub Actions
workflow (workflow_dispatch), or run `python run_report.py` locally after
`python run_ingestion.py` has populated the database — no code editing
required either way.

This step never fetches live data itself (see run_ingestion.py for that);
it only reads whatever has already been ingested, checks the data-quality
gate, and — if the gate passes — runs the engine and persists/publishes
the result. A failing gate blocks publication and leaves the previous
valid report untouched.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from service.config import AppConfig, load_dotenv
from service.db import get_session_factory, init_db
from service.orchestrator import run_market_priority_report
from service.universe import load_universe


def main(argv=None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", help="YYYY-MM-DD; defaults to today")
    ap.add_argument("--universe-file", help="One ticker per line; defaults to the built-in list")
    ap.add_argument("--output", default="output")
    args = ap.parse_args(argv)

    config = AppConfig.from_env()
    engine = init_db(config.database_url)
    session_factory = get_session_factory(engine)
    universe = load_universe(args.universe_file)
    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else dt.date.today()

    with session_factory() as session:
        result = run_market_priority_report(session, universe, as_of, args.output)

    print(f"[{result.status}] {result.message}")
    if result.status != "published":
        for failure in (result.gate.failures if result.gate else []):
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"report_id={result.report_id} as_of={result.as_of_date} -> {args.output}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
