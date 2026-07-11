#!/usr/bin/env python3
"""Print the full, unfiltered factor x macro interaction table and per-factor
rolling stats from a completed engine run.

market_priority_report.md deliberately narrates only FDR-surviving
interactions (docs/QUANT_METHODOLOGY.md: "the narrative may only discuss
survivors") -- that discipline exists to stop noise from being presented as
signal. This script exists for the opposite, complementary need: seeing the
raw beta/t/q for every pair tested, survivor or not, so a human can judge
which relationships look directionally interesting even though none of them
individually cleared the statistical bar this run. Treat non-surviving rows
as exploratory, not validated -- that's the whole point of the bar they
didn't clear.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="output")
    args = ap.parse_args(argv)

    itests_path = os.path.join(args.output, "interaction_tests.csv")
    fscores_path = os.path.join(args.output, "factor_scores.csv")

    if os.path.exists(itests_path):
        try:
            itests = pd.read_csv(itests_path)
        except pd.errors.EmptyDataError:
            itests = pd.DataFrame()
        print("\n=== All factor x macro interaction pairs tested (sorted by q-value) ===")
        print("FDR-surviving rows are also narrated in market_priority_report.md; the "
              "rest are raw exploratory evidence -- not validated by the FDR gate.\n")
        if itests.empty:
            print("(no pairs had enough history to test)")
        else:
            cols = ["factor", "macro_state", "interaction_beta", "t_stat", "p_value",
                    "q_value", "significant_fdr", "n_periods"]
            print(itests.sort_values("q_value")[cols].to_string(index=False))

    if os.path.exists(fscores_path):
        fscores = pd.read_csv(fscores_path, parse_dates=["date"])
        latest = fscores[fscores["date"] == fscores["date"].max()].copy()
        latest["abs_t"] = latest["rolling_ic_t"].abs()
        print("\n=== Latest per-factor rolling stats (sorted by |t|) ===\n")
        cols = ["factor", "rolling_ic", "rolling_ic_se", "rolling_ic_t", "hit_rate",
                "strengthening_4p"]
        print(latest.sort_values("abs_t", ascending=False)[cols].to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
