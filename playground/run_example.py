#!/usr/bin/env python3
"""Run a playground technical-strategy backtest against real ingested price
history. Not part of the audited pipeline -- see playground/README.md.

Examples:
  python playground/run_example.py --ticker AAPL --strategy ma_crossover --start 2015-01-01
  python playground/run_example.py --ticker AAPL --strategy rsi_reversion --start 2015-01-01 --plot
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys

from backtest import plot_equity_curve, print_metrics, run_backtest
from data import load_daily_prices


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--strategy", required=True,
                    help="Module name under playground/strategies/, e.g. ma_crossover")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "output"))
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    prices = load_daily_prices(args.ticker, start=args.start, end=args.end)

    strategy_module = importlib.import_module(f"strategies.{args.strategy}")
    signal = strategy_module.generate_signal(prices)

    metrics = run_backtest(prices, signal)
    print_metrics(args.ticker, args.strategy, metrics)

    if args.plot:
        os.makedirs(args.output, exist_ok=True)
        out_path = os.path.join(args.output, f"{args.ticker}_{args.strategy}.png")
        plot_equity_curve(args.ticker, args.strategy, metrics["equity_curve"], out_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
