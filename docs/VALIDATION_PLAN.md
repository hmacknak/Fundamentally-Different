# Validation Plan

## Engineering validation
- Unit tests for factor derivations, ranking, lag rules, ICs, FDR, and report rendering
- Golden-file tests using the current synthetic outputs
- Deterministic seeded control tests in CI
- Schema and null-rate checks on every ingestion

## Research validation
- Planted-signal recovery and null specificity tests
- Walk-forward train/test separation
- Window sensitivity: 4, 8, 12, and 16 periods
- Fundamental lag sensitivity: 45, 60, 90 days
- Rebalance sensitivity: monthly and quarterly
- Sector-neutral and non-neutral comparisons
- Universe robustness across at least two universes
- Stability of factor signs and theme rankings

## Bias controls
- Look-ahead bias
- Survivorship bias
- Restatement bias
- Delisting and corporate-action handling
- Benchmark consistency
- Data snooping and multiple testing

## Publication gate
A report may be marked valid only when required data freshness, coverage, minimum observations, and control tests pass. Otherwise it must be labelled experimental or blocked.
