# Quantitative Methodology

## Existing design to preserve
- Cross-sectional factor ranks at each rebalance date
- Forward benchmark-relative returns
- Rolling mean information coefficient (IC)
- Standard error, t-statistic, and hit rate
- Priority themes composed from factor evidence
- Per-date cross-sectional factor payoff estimation
- Time-series regression of factor payoffs on macro states
- Benjamini–Hochberg FDR control across interaction tests
- Stock ranking only after priority scores are estimated

## Point-in-time rules
- A fundamental observation may enter only after its recorded availability date.
- If availability date is unavailable, apply the configured conservative lag and flag the limitation.
- Macro normalization must use expanding or trailing information only.
- Universe membership must be as-of-date when historical membership data becomes available.

## Required additions
- Bootstrap confidence intervals for priority scores
- Quantitative trend magnitude, not only labels
- Change tables versus prior rebalance
- Sensitivity runs for window length, lag, and rebalance frequency
- ~~Walk-forward out-of-sample evaluation~~ — done: `amp/walkforward.py`
  ranks stocks at each historical rebalance date using only that date's
  (already trailing-only) priority scores, then measures realized forward
  excess return. Reported in `market_priority_report.md` and
  `walk_forward_results.csv` with an explicit small-sample warning below
  20 periods. Turnover/costs (next item) are still not modeled, so read
  these numbers as a directional check, not a strategy return estimate.
- Turnover and transaction-cost analysis before any strategy claims

## Methodology changes (documented per CLAUDE.md rule 1)

### 2026-07-11 — Priority ranking weights now trailing-averaged, not latest-snapshot-only
- What changed: `amp/priorities.py:composite_stock_ranks` previously set each
  priority's ranking weight from that single rebalance date's
  `priority_score`. It now averages `priority_score` over the trailing
  `weight_smoothing_periods` dates (default 4, i.e. ~1 year at quarterly
  rebalancing) up to and including the ranking date. Configurable via
  `--weight-smoothing-periods`; recorded in `audit_trail.json`'s config.
- Why: the real 38-quarter walk-forward run showed a mechanical "chasing"
  loop — `momentum_6m` is a member of the "Growth scarcity" priority, so a
  quarter with strong recent price appreciation mechanically inflates that
  priority's IC and thus its ranking weight, which then ranks even more
  heavily by trailing momentum next quarter. Averaging over several trailing
  quarters is a standard, easily-audited way to damp single-period noise in
  a weighting scheme.
- What did NOT change: which factors compose which priority (`PRIORITY_MAP`),
  how rolling IC itself is computed, point-in-time discipline (the averaging
  window only ever looks at dates `<= ` the ranking date), or FDR control.
  This changes portfolio *weighting*, not the underlying factor evidence or
  diagnosis.
- Consequences: ranking weights react more slowly to a single hot or cold
  quarter. Verified against both synthetic control tests (planted-signal
  recovery unaffected) before running against real data.

### 2026-07-11 — Walk-forward headline stat now also reported winsorized
- What changed: `amp/walkforward.py:summarize_walk_forward` now returns a
  second set of stats (`*_winsorized`) alongside the existing raw ones,
  capping each tail of the per-period returns at the 5th/95th percentile
  (`WINSORIZE_LIMIT`) before computing the mean/SE/t-stat. The raw stats are
  unchanged and always reported first — winsorizing is a robustness view,
  never a silent replacement.
- Why: the real 38-quarter result had 2 outlier quarters (both large
  momentum-driven moves) materially driving the headline mean; a reader
  needs to see how much of the stat depends on a handful of periods.
- Consequences: purely a measurement/reporting change — it does not alter
  any ranking, weighting, or FDR behavior, only how the walk-forward summary
  stat is presented.

## Interpretation rule
Statistical significance alone is insufficient. Each narrated relationship must have:
1. FDR survival where applicable;
2. adequate observations and coverage;
3. stable sign under basic sensitivity checks;
4. a clearly labelled economic interpretation or an explicit “mechanism unknown” warning.
