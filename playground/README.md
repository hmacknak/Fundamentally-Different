# Playground

A sandbox for messing around with classic technical-analysis strategies on
daily price data, for fun — completely separate from the Adaptive Market
Priority Engine's actual research pipeline.

**This is not part of the audited product.** Nothing here is imported by
`amp/`, `adaptive_market_priority_engine.py`, `service/`, or any
`.github/workflows/*.yml`. It carries none of AMPE's guarantees:

- Not point-in-time controlled beyond a basic one-bar signal shift.
- Not FDR-corrected or multiple-testing-aware.
- Not reviewed against the acceptance criteria in `docs/ACCEPTANCE_CRITERIA.md`.
- Never feeds the Market Priority Report, never changes any ranking or
  weighting logic in `amp/`.

Treat anything printed here as "interesting to look at," not as investment
research.

## Setup

Uses the same database the production pipeline already populates
(`DATABASE_URL`, same as everywhere else in this project) — no new data
fetching. Only extra dependency is `matplotlib`, for optional equity-curve
plots:

```bash
pip install -r playground/requirements.txt
```

## Usage

```bash
python playground/run_example.py --ticker AAPL --strategy ma_crossover --start 2015-01-01
python playground/run_example.py --ticker AAPL --strategy rsi_reversion --start 2015-01-01 --plot
```

## Adding a new strategy

Add a new file under `playground/strategies/` exposing:

```python
def generate_signal(prices: pd.Series) -> pd.Series:
    """Return a position per day (e.g. -1/0/1), aligned to `prices`' index."""
```

`playground/backtest.py` takes care of shifting the signal by one bar
before applying it to next-day returns and computing the metrics.
