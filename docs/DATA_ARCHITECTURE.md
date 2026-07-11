# Data Architecture

## Data domains
### Prices
- date, ticker, adjusted close, volume
- corporate-action-adjusted total-return series preferred

### Fundamentals
- period end
- filing date / accepted date / availability date
- revenue, EBIT, EBITDA, net income, cash flow, debt, cash, shares
- derived factors must be computed internally where possible

### Macro
- observation date, release date when available, value, source
- rates, inflation, credit spreads, volatility, commodities, FX, benchmark

### Universe
- ticker, security identifier, membership start/end, sector, benchmark

## Storage model
Use a small relational database for MVP, preferably PostgreSQL in production and SQLite for local tests.

Core tables:
- `security_master`
- `universe_membership`
- `prices_daily`
- `fundamentals_reported`
- `macro_observations`
- `data_ingestion_runs`
- `research_runs`
- `factor_scores`
- `priority_scores`
- `interaction_tests`
- `security_ranks`
- `published_reports`

## Lineage
Every row ingested must retain provider, retrieval timestamp, source key, and raw payload hash. Every research run must retain configuration, code commit SHA, input snapshot identifiers, warnings, and output hashes.

## Provider strategy
Create provider interfaces so the system can begin with inexpensive sources and later replace them without rewriting the research engine.
