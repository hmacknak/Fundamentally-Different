# Adaptive Market Priority Engine

Diagnoses what the market currently appears to be **optimizing for** (cash
generation, balance-sheet strength, growth scarcity, valuation discipline, risk
avoidance, inflation protection, capital discipline), identifies **which company
criteria** satisfy that priority, tests whether those criteria are actually being
**rewarded in forward benchmark-relative returns**, and whether the relationship
is **strengthening or weakening**. Stock ranking is strictly downstream of the
diagnosis. Research tool — not investment advice, no trading.

## Validation status (control tests — run them yourself)

Planted-signal recovery on synthetic data, 3 seeds:

| Test | Seed 42 | Seed 7 | Seed 123 |
|---|---|---|---|
| fcf_yield x credit_spread interaction (planted) | RECOVERED t=7.2 | RECOVERED t=3.7 | RECOVERED t=7.9 |
| revenue_growth steady payoff (planted) | RECOVERED t=2.6 | RECOVERED t=1.9 | RECOVERED t=2.1 |
| Null run (zero effects) | 0 FDR survivors — specificity PASSED | | |

Unplanted FDR survivors appear at the promised controlled rate (q<=0.10) and are
auto-annotated with their correlation to planted factors.

```bash
# planted-signal control test
python adaptive_market_priority_engine.py --synthetic --output output

# specificity control test (zero planted effects; engine should find ~nothing)
python adaptive_market_priority_engine.py --synthetic-null --output output_null
```

## Run on real data

```bash
python adaptive_market_priority_engine.py \
  --prices prices.csv --fundamentals fundamentals.csv --macro macro.csv \
  --output output --rebalance Q --holding-months 3 --rolling-windows 8 \
  --top-n 20 --fundamental-lag-days 60
```

Optional: `--sector-neutral` (rank factors within sector), `--fdr 0.10`,
`--rebalance M`.

## Input schemas

- `prices.csv`: date, ticker, adj_close, volume (daily)
- `fundamentals.csv`: date, ticker, fcf_yield, debt_to_equity, roe,
  revenue_growth, pe, ev_ebitda, dividend_yield
  (+ optional: interest_coverage, gross_margin, operating_margin,
  free_cash_flow_margin, eps_revision, shares_dilution, sector)
- `macro.csv`: date (monthly), benchmark_adj_close, rate_10y, rate_2y, cpi_yoy,
  wti_oil, vix, credit_spread, cadusd, gold

`data_adapters.py` builds all three from live sources (yfinance + FRED free;
FMP for fundamentals, paid). The vendor-mapping logic (service/providers/)
is unit tested against canned responses, but the live network calls
themselves haven't been exercised against the real APIs yet — expect minor
field-name fixes on first live run.

## Automated pipeline (Phase 1)

For the "run without touching code" MVP described in docs/PRD.md:

```bash
pip install -r requirements.txt
python -m pytest                 # 73 tests: math, DB schema, ingestion, orchestrator
python run_ingestion.py           # fetch live prices/macro (+ fundamentals if FMP_API_KEY is set)
python run_report.py              # gate-checked engine run -> report, or a clear "blocked" reason
```

`run_report.py` never publishes from stale or thin data — see
`service/ingestion.check_data_quality_gate` and docs/VALIDATION_PLAN.md's
publication gate. Configuration is env-based (`service/config.py`,
`config/example.env`); `.github/workflows/ingest.yml` and
`publish-report.yml` scaffold the daily/quarterly schedule from
docs/AUTOMATION_AND_DEPLOYMENT.md but need `DATABASE_URL` and
`FMP_API_KEY` added as repo secrets before they do anything beyond a dry
run — see docs/DECISIONS.md, "Open items requiring the owner."

## Outputs (per run, in --output)

- `market_priority_report.md` — plain-English report; hedged language enforced;
  only FDR-surviving interactions are narrated
- `priority_scores.csv`, `factor_scores.csv` (rolling IC ± SE, t, hit rate,
  strengthening), `interaction_tests.csv` (b, t, p, q, FDR flag),
  `latest_stock_ranks.csv`, `panel_rebalance_data.csv`
- `data_quality_report.md`, `audit_trail.json` (config, input SHA-256 hashes,
  environment, runtime)

## Integrity rules built in

1. **Point-in-time discipline** — fundamentals enter a rebalance only after a
   configurable reporting lag (default 60 days); macro states use expanding
   z-scores (no full-sample look-ahead).
2. **Excess returns** — all evidence is benchmark-relative, not raw.
3. **Multiple-testing control** — all factor x macro tests corrected with
   Benjamini-Hochberg FDR; the narrative may only discuss survivors.
4. **Honest interaction estimation** — per-date cross-sectional payoff slopes,
   then time-series regression on macro states (macro is constant within a
   date, so pooled cross-sectional interactions are not identified).
5. **Priority overlap disclosure** — shared-evidence Jaccard matrix published;
   correlated diagnoses are labeled as such.
6. **Every stat ships with uncertainty** — SE, t, q, n throughout.

## Known limitations / next build items

- Survivorship: yfinance serves today's listings; reconstruct historical index
  membership before trusting multi-year stats (S&P 500 change log is public).
- Fundamentals vintage: FMP key-metrics can reflect restatements; prefer
  as-reported endpoints; future improvement — use filing dates as the as-of key.
- No transaction costs, no portfolio construction, no out-of-sample walk-forward
  yet (deliberate: diagnosis first, strategy later).
