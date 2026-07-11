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
- Walk-forward out-of-sample evaluation
- Turnover and transaction-cost analysis before any strategy claims

## Interpretation rule
Statistical significance alone is insufficient. Each narrated relationship must have:
1. FDR survival where applicable;
2. adequate observations and coverage;
3. stable sign under basic sensitivity checks;
4. a clearly labelled economic interpretation or an explicit “mechanism unknown” warning.
