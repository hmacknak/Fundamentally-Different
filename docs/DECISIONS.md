# Architecture and Research Decisions

Record decisions here using:

## YYYY-MM-DD — Decision title
- Context
- Decision
- Alternatives considered
- Consequences
- Owner

Initial decisions:
- Preserve the current modular research engine as the reference implementation.
- Build provider adapters around the engine rather than embedding vendor logic inside research modules.
- Start with a smaller universe and rigorous failure handling before expanding coverage.

## 2026-07-11 — Absorbed Phase 0 into the start of Phase 1
- Context: asked to start Phase 1 ("Automated real-data MVP"), but CLAUDE.md's
  build contract and START_HERE_FOR_CLAUDE.md both require the first PR to be
  "reproducible installation, tests, configuration, and CI hardening" and
  explicitly forbid vendor integration in that first PR. The imported
  prototype had a dependency file and a CI smoke test but zero unit tests and
  no structured configuration — Phase 0's roadmap items were not actually done
  yet despite looking superficially complete.
- Decision: did Phase 0 stabilization first (41 pytest tests locking down the
  statistics and control-test behavior, ruff-clean, service/config.py for
  env-based configuration) before starting any of Phase 1's data/database/
  automation work. Framed as sequencing, not scope-cutting — Phase 1 work
  proceeded immediately after in the same session.
- Alternatives considered: build Phase 1 first and backfill tests later. Rejected
  because CLAUDE.md rule 2 ("never weaken point-in-time controls ... or
  auditability") and the working-style rule ("add tests before refactoring
  critical math") make an untested baseline the wrong foundation to build a
  database and ingestion pipeline on top of.
- Consequences: two extra commits before Phase 1 code appears, but every
  subsequent change (DB schema, provider adapters, ingestion, orchestrator) had
  a green test suite to change against, which caught three real bugs (below)
  before they reached main.
- Owner: engineering (no owner input needed — no cost, no account, no
  methodology change).

## 2026-07-11 — SQLite for the MVP database, Postgres deferred
- Context: docs/DATA_ARCHITECTURE.md calls for "PostgreSQL in production and
  SQLite for local tests." A hosted Postgres instance needs an external
  account and, on most providers, a paid tier or usage-based billing.
- Decision: SQLite (file-based, no account, no cost) is the default and only
  target for this Phase 1 start. All schema is defined in
  service/db/models.py via SQLAlchemy against DATABASE_URL, so pointing that
  URL at a managed Postgres instance later requires no model changes.
- Alternatives considered: provisioning a free-tier managed Postgres (Neon,
  Supabase, Railway) now. Deferred — that is an account-creation decision
  for the owner, not something to do silently on their behalf.
- Consequences: works fully offline/in CI today. On GitHub Actions' ephemeral
  runners, a SQLite file does not persist between scheduled runs — ingestion
  history resets every run until DATABASE_URL points at a real, persistent
  database. See "Open items requiring the owner" below.
- Owner: owner decision needed before scheduled automation is meaningful.

## 2026-07-11 — Migrations deferred in favor of create_all()
- Context: docs/DATA_ARCHITECTURE.md says "database schema and migrations."
- Decision: service/db/session.py's init_db() creates tables with
  Base.metadata.create_all(), which is idempotent but has no upgrade/rollback
  story for schema changes.
- Alternatives considered: wiring Alembic now. Deferred as premature — the
  schema has not yet been run against a single real ingestion cycle, and
  Alembic migrations for a schema that's still likely to change would mean
  rewriting migration history repeatedly.
- Consequences: fine for local/dev SQLite; before pointing this at a
  persistent Postgres with real data, add Alembic so schema changes don't
  require dropping tables.
- Owner: engineering, before "go live" on a persistent database.

## 2026-07-11 — FRED adapter keeps using the public CSV export, not fredapi
- Context: requirements.txt listed `fredapi` (the official FRED client
  library, which needs a free FRED account/API key) but no code imported it —
  data_adapters.py has always fetched FRED series via the public
  `fredgraph.csv` export, which needs no account.
- Decision: kept the public-CSV approach (service/providers/fred.py) and
  removed the unused `fredapi` dependency rather than switching to it.
- Alternatives considered: switching to the official fredapi package for a
  more stable/documented API. Rejected for now — it would add an account
  requirement for data that's currently free and already works; noted as an
  available upgrade path if the public CSV export ever becomes unreliable.
- Consequences: one less dependency; macro ingestion (rates, CPI, credit
  spread, WTI) needs no API key at all. Only FMP (fundamentals) does.
- Owner: engineering.

## 2026-07-11 — Default universe is a static, documented placeholder list
- Context: docs/PRD.md specifies "configurable U.S. large-cap list, initially
  50-100 names" and CLAUDE.md rule 7 says the owner must not need to edit
  configuration.
- Decision: service/universe.py ships a hard-coded large-cap list so the
  system runs out of the box. A developer can override it via
  --universe-file; the non-technical owner never needs to.
- Alternatives considered: requiring the owner to supply a universe on first
  run. Rejected — violates the "no recurring technical work" product
  principle.
- Consequences: this list is not an investment recommendation and carries the
  same survivorship caveat already documented in README.md (today's listings
  only); expanding/rotating the universe is a code change, not a methodology
  change.
- Owner: engineering; revisit if the owner wants a different starting universe.

## 2026-07-11 — Expanded default universe from 61 names to the full S&P 500
- Context: after the first successful real report (61 tickers), the owner
  asked to expand coverage to get more cross-sectional statistical power —
  more tickers per rebalance date, not a methodology change.
- Decision: replaced the hand-curated 61-ticker list with all 503 current
  S&P 500 constituents, sourced from the "datasets/s-and-p-500-companies"
  community-maintained GitHub dataset (this environment couldn't fetch
  Wikipedia's source list directly — 403s from its bot protection).
- Verification: spot-checked tickers against known symbols before shipping.
  Found and corrected one transcription error in the source dataset (Marsh
  & McLennan listed as "MRSH"; corrected to "MMC", its real ticker). Also
  confirmed several unfamiliar-looking entries are genuine recent (2025-2026)
  corporate actions, not errors: FDXF (FedEx Freight spinoff), HONA
  (Honeywell Aerospace, post 3-way split), Q (DuPont's Qnity Electronics
  spinoff). Not exhaustively re-verified beyond that spot check.
- Consequences: ~350 API calls/day of headroom matters more now — FMP
  Starter's rate limit is 300 calls/minute, and full-universe ingestion now
  makes ~1,006 FMP calls (503 tickers x 2 endpoints) per run, so this is
  comfortably within the per-minute limit but worth watching if a daily cap
  applies. Any ticker this list gets wrong simply gets skipped by the
  provider fetch (already-existing per-ticker error handling), not a crash —
  so residual errors degrade coverage slightly rather than break the run.
- Owner: engineering; re-verify the ticker list periodically as constituents
  change (this is exactly the survivorship-membership problem already
  flagged as a Phase 2 item).

## 2026-07-11 — Open items requiring the owner
None of these block the code already written — everything above is tested
and works fully offline. They block turning the scheduled GitHub Actions
workflows (.github/workflows/ingest.yml, publish-report.yml) into something
that actually keeps running and accumulating history. Per this project's
build instructions, these are flagged rather than decided silently because
each needs an external account, and one costs money:

1. **FMP_API_KEY** (costs money, ~US$20-30/month) — required for
   fundamentals data (fcf_yield, debt_to_equity, roe, etc.). Without it,
   run_ingestion.py skips fundamentals with a warning and prices/macro
   ingestion still works; the data-quality gate will then correctly block
   report publication on insufficient fundamentals coverage. Needed once
   real (non-synthetic) reports are wanted.
2. **DATABASE_URL pointing at a persistent database** (requires creating an
   account with a database host) — GitHub Actions runners are ephemeral, so
   without this, every scheduled run starts from an empty database and
   nothing accumulates day-to-day. A free-tier managed Postgres (e.g. Neon,
   Supabase, Railway) would work; this is a "pick one and create an account"
   decision for the owner, not something to choose on their behalf.
3. **Adding both as GitHub Actions secrets** (Settings → Secrets and
   variables → Actions → New repository secret) — requires repo admin
   access, which only the owner (or someone they authorize) has.
4. **Persistent report storage/hosting** for "the latest valid report is
   retained and queryable" (ACCEPTANCE_CRITERIA.md) beyond the 90-day GitHub
   Actions artifact default — depends on the DATABASE_URL decision above
   (published_reports rows already point at file paths; those files need
   somewhere durable to live once DATABASE_URL is persistent).

Until an owner decision lands on 1-2, the scheduled workflows will run
without erroring but will reliably report "blocked" (empty database) rather
than publish a live report — this is the data-quality gate working as
designed, not a bug.

## 2026-07-11 — Two conservative fixes for momentum "chasing" behavior
- Context: after the first real S&P 500 walk-forward result (38 quarters,
  +4.47%/qtr, t=2.43), the owner pushed on how much of that was momentum
  chasing itself: `momentum_6m` is a member factor of the "Growth scarcity"
  priority, and ranking weights were set from only the single latest
  rebalance date's priority score. A hot momentum quarter mechanically
  inflates Growth scarcity's IC that quarter, which raises its ranking
  weight, which ranks even more heavily by trailing momentum next quarter —
  a self-reinforcing loop, not necessarily a real signal. Excluding the 2
  largest outlier quarters from the raw walk-forward sample dropped the mean
  from +4.47%/qtr to +2.44%/qtr (t=1.98), confirming a small number of
  periods were doing a lot of work.
- Decision: shipped the two safest fixes of four considered, per the owner's
  explicit go-ahead, and held off on the more invasive ones:
  1. **Weight smoothing** (`amp/priorities.py`): priority ranking weights now
     use a trailing 4-quarter average of `priority_score` instead of only
     the latest date, configurable via `--weight-smoothing-periods`. See
     docs/QUANT_METHODOLOGY.md for the full writeup.
  2. **Winsorized walk-forward reporting** (`amp/walkforward.py`): the
     walk-forward summary now reports a winsorized (5th/95th percentile
     capped) mean/SE/t alongside the existing raw ones, so the report makes
     outlier-driven results visible rather than hiding them behind one
     number. Never replaces the raw stat.
- Alternatives considered (deferred, not approved): (a) a turnover/
  rank-persistence rule penalizing single-quarter rank churn, and (b)
  decoupling momentum from the ranking weight entirely (e.g. giving it a
  measurement-only role, not a weight-setting one). Both are real
  methodology changes to the diagnosis itself, not just the weighting/
  reporting layer, and were explicitly held back until the effect of these
  two conservative fixes on real data is visible.
- Consequences: this changes portfolio ranking *weights*, not factor
  evidence, priority composition, or FDR control. Verified against synthetic
  control tests (planted-signal recovery unaffected) before touching real
  data; the number of rebalance dates evaluated is unchanged, only weight
  computation and summary-stat reporting change.
- Owner: engineering (per owner's explicit "Yes" approval); revisit items
  (a)/(b) above once real-data walk-forward results with the smoothed
  weights have accumulated a few more quarters.

## 2026-07-11 — Reactive-vs-predictive architecture review; persistence diagnostic shipped first
- Context: the owner challenged the core architecture directly: AMPE ranks
  stocks by which characteristics the market *has recently rewarded*
  (trailing-average payoff), which is economically reactive, not
  predictive — the Nvidia/Growth-scarcity example (an already-800%-up stock
  getting ranked highly because momentum recently paid off) illustrates the
  concern precisely. The owner proposed forecasting the macro path 3-12
  months out and ranking on that forecast instead, and asked for a rigorous,
  skeptical evaluation before any code changed.
- Finding: the criticism of the *current* architecture is correct — ranking
  weights are set from realized past payoff applied to today's exposures,
  a momentum-in-factor-returns rule, and last session's smoothing fix
  reduced its variance, not its direction. But the proposed cure (forecast
  macro variables) is very likely a *worse* problem: macro forecasting at
  this horizon is one of the least reliable prediction tasks in finance,
  and would add a second, noisier estimation layer with a much larger
  hindsight-bias surface than the existing FDR-gated factor evidence.
  Critically, `amp/interactions.py` already estimates a genuinely
  forward-conditional quantity — a factor's expected payoff conditional on
  *today's already-known* macro state (no forecasting needed) — but that
  estimate is never fed into `priorities.py`'s ranking weights, which use
  only the unconditional trailing average. The real fix is reconnecting
  evidence the project already validates, not building a macro forecaster.
- Decision: reject macro-path forecasting. Plan a regime-conditional,
  shrinkage-blended weighting scheme instead (blend the existing trailing
  average with the FDR-surviving conditional payoff estimate evaluated at
  today's macro state, shrunk toward the trailing average based on how much
  history supports the conditional estimate). Before designing that blend,
  ship a diagnostic that should have gated last session's smoothing fix:
  does a factor's realized payoff actually persist quarter to quarter
  (`amp/persistence.py`, lag-1/lag-4 autocorrelation of the raw per-date
  `ic`, FDR-corrected jointly across factors and lags)? If it mean-reverts
  instead, trailing-average weighting is wrong in *direction*, not just
  noisy — a materially different and more urgent finding than anything
  addressed so far.
- Alternatives considered: designing the shrinkage weighting immediately
  (deferred — would repeat the "assume, don't test" pattern this review is
  critiquing); a valuation-spread-based forward signal a la factor-timing
  literature (noted as a possible future complement, not pursued now — adds
  complexity before the simpler, already-available fix is even tried).
- Consequences: this entry documents a diagnostic only
  (`amp/persistence.py`, reported in `market_priority_report.md` and
  `factor_persistence.csv`) — no ranking or weighting behavior changed.
  The regime-conditional shrinkage weighting itself is not yet built; it is
  explicitly gated on this diagnostic's real-data result, per the owner's
  "do what you think" on sequencing.
- Owner: engineering; the shrinkage-weighting design (next phase) should
  be reviewed with the owner before it changes real ranking behavior, per
  CLAUDE.md rule 1.

## 2026-07-11 — Known defects found and fixed while stabilizing
- `adaptive_market_priority_engine.py`: nested f-strings with matching
  quotes (Python 3.12+ only) broke `--synthetic-null` on the documented
  Python 3.11 target. Fixed by extracting the inner comprehension to a
  variable. No output change.
- `data_adapters.py`: `build_fundamentals_csv` computed an always-None
  `_shares` field behind an `if False` — dead code left over from an
  unfinished shares-outstanding feature. Removed; `shares_dilution` stays
  None with a comment that FMP's key-metrics/ratios endpoints don't carry a
  shares-outstanding history to derive it from honestly.
- `service/ingestion.py`: `_upsert`'s `model(**natural_key, **values)`
  raised `TypeError: got multiple values for keyword argument` whenever a
  field (here, `provider`) appeared in both dicts — true for every
  fundamentals row. Caught by its own test; fixed by merging the dicts
  before construction.
- `service/orchestrator.py`: persistence crashed reading
  `interaction_tests.csv` with `EmptyDataError` whenever too few rebalance
  periods exist for any factor x macro pair to reach `min_obs` (a near-empty
  but non-zero-byte CSV) — a realistic state early in a deployment's life,
  not an error condition. Caught by the end-to-end orchestrator test; now
  treated as a valid zero-interactions result.

## 2026-07-17 — Nightly ingestion filled the 512MB DB cap; made ingestion incremental
- Problem: the scheduled `ingest.yml` run failed with
  `psycopg2.errors.DiskFull: could not extend file because project size
  limit (512 MB) has been exceeded`, which also broke the same day's
  `publish-report.yml` run (the data-quality gate correctly refused to
  publish from prices it couldn't update — working as intended, not a
  second bug).
- Root cause: `run_ingestion.py` hardcoded `--start 2015-01-01` and never
  advanced it based on existing DB coverage. Every scheduled run re-fetched
  and re-upserted full history for the whole ~503-ticker universe, so all
  ~1.49M `prices_daily` rows were rewritten every night via
  `ON CONFLICT DO UPDATE` — including `retrieved_at`/`raw_payload_hash`,
  which `_bulk_upsert` always touched even when the underlying price was
  byte-identical to what was already stored. With a table already near
  capacity from live data alone, ~83 days of full-table daily rewrites and
  no retention/VACUUM policy produced enough MVCC dead-tuple bloat to push
  the database over its host-enforced 512MB cap.
- Fix (`service/ingestion.py`, `run_ingestion.py`, `data_adapters.py`):
  - `compute_incremental_start()` resumes each of prices/macro from the day
    after the *earliest* "latest observed date" across the universe/series
    (not the latest, so a straggler that missed a day still catches up),
    falling back to `--start` when coverage is incomplete (empty table, or
    a ticker/series with no rows at all yet, e.g. newly added to the
    universe). `run_ingestion.py` uses this by default; a new
    `--full-backfill` flag (also exposed as a `workflow_dispatch` boolean
    input on `ingest.yml`) forces the old full-refetch behavior for a
    deliberate one-time backfill or recovery.
  - `_bulk_upsert()` gained an optional `change_detection_columns` guard
    (`ON CONFLICT ... WHERE <col> IS DISTINCT FROM excluded.<col>`): a
    conflicting row is only actually rewritten when a real value changed.
    Applied to prices (`adj_close`, `volume`), macro (`value`), and
    fundamentals (all reported fields). A genuine change (price revision,
    fundamentals restatement) still rewrites lineage columns in full —
    this narrows *no-op* rewrites only, so CLAUDE.md rule 4's provenance
    contract (source/retrieved_at/effective/availability date per field)
    is unaffected for any row whose value actually changed.
  - `prune_ingestion_runs()` (default `keep_days=90`), called once per
    ingestion run, bounds the append-only `data_ingestion_runs` log (one
    observed failed run wrote a ~75KB `error_message`). This is operational
    logging, not point-in-time financial data, so bounding its retention
    does not weaken auditability under rule 2.
  - `build_fundamentals_csv` takes no `start`/`end` at all — it always
    pulls FMP's last `limit` periods per ticker regardless of DB state, so
    its fetch size was already bounded; only the no-op-upsert guard applies
    to that domain, not incremental start.
- Not yet done (operational, not code): the database is still at its
  512MB cap as of this fix landing. Recovering existing space needs a
  manual, confirmed `VACUUM` pass against the live database (plain
  `VACUUM`, not `VACUUM FULL`/`pg_repack` — those need temporary headroom
  a full database may not have) and, if that's insufficient, a temporary
  storage-limit bump from the DB host. This is a deliberate prod
  operation requiring the owner's go-ahead, not something to script into
  CI. Until it happens, the next scheduled ingestion run may still fail
  on write even though the rewrite-everything bug is fixed, simply because
  there's no free space left for the catch-up window's genuinely new rows.
- Verification: `tests/test_ingestion.py` and `tests/test_run_ingestion_cli.py`
  cover incremental-start resumption, the straggler/incomplete-coverage
  fallback, the no-op-skip behavior for prices/macro, `--full-backfill`,
  and `prune_ingestion_runs`. Full suite (109 tests) and `ruff check .`
  pass. Not yet verified against the live Postgres database, since it has
  no free space to write to until the VACUUM step above happens.

## 2026-10-02 — Playground BOS/CHoCH intraday backtest (SPY 1m) added

- Context: the owner asked for a backtest of a Smart-Money-Concepts style
  intraday strategy (BOS + CHoCH, enter on the retest of the CHoCH level,
  stop below the prior low, 1:1 target) on SPY 1-minute bars and higher
  timeframes. A spec was drafted in a separate chat, but its code
  (`backtest_smc.py`, `run_spy.py`) was never committed here, so it was
  rebuilt from that spec under `playground/smc/`.
- Decision: keep it in `playground/` (not `amp/`). It touches no AMPE
  module, database or report, and carries none of AMPE's guarantees.
- Exception to `playground/README.md`: a dedicated workflow
  (`.github/workflows/smc-backtest.yml`) runs it. The development sandbox
  can't reach any market-data host, and the owner can't be expected to
  run Python locally (CLAUDE.md rule 7). The workflow is self-contained,
  needs no secrets and touches no AMPE job.
- Data: Yahoo 1m via yfinance, ~30 days only, with provenance (source and
  retrieval time) written to `data_provenance.json`. If the download
  returns nothing, the job fails rather than falling back to synthetic data.
- Owner answers (2026-10-02): the stop goes below the low that started the
  move (origin low), and 1m structure resets each session. Both match the
  implementation. The owner then confirmed the BOS/CHoCH logic
  is correct, so the strategy definition is locked. Any later rule changes
  count as new variants and must be tracked for multiple-testing purposes. A year-plus 1m data source (Polygon or
  Alpaca, both need a key) is needed before any result means anything.

## 2026-10-02 — First multi-year SMC backtest result (SPY, Alpaca SIP, 5 years)

- Run: [Actions run 36947342328](https://github.com/hmacknak/Fundamentally-Different/actions/runs/36947342328),
  2021-10-04 .. 2026-10-01, 1,254 sessions, 488,644 regular-hours 1m bars
  (about 99.9% of the expected 390 bars per session). Locked rules, default
  parameters, no tuning. Holdout = 2025-10-01 .. 2026-10-01.
- Result, net R per trade (t-stat):
  - 1m: 1,378 trades, -0.014R (t -0.52). In-sample -0.036R (t -1.18),
    holdout +0.080R (t +1.33).
  - 5m: 365 trades, +0.058R (t +1.20). In-sample +0.049R (t +0.92),
    holdout +0.096R (t +0.87).
  - 15m/30m/60m: 55, 18 and 6 trades, too few to judge.
- Conclusion: no statistically meaningful edge at any timeframe. Five
  timeframes were compared, so the best row (5m, t 1.2) is well within
  what chance alone produces. 5m is the only row positive in both periods.
  It is a candidate for a pre-registered follow-up, not a tradeable result.
- 1m dollar return (+0.16%) and total R (-19.5) disagree in sign because
  the 4x leverage cap shrinks size on tight stops. R is the fairer measure.

## 2026-10-02 — Pre-registered variant search for the SMC strategy

Written and committed before any result was seen. The protocol lives in
`playground/smc/research_smc.py` and must not be edited after the run.

- Data: Alpaca SIP 1m SPY, last 5 years. In-sample is everything before
  the last 12 months; holdout is the last 12 months.
- Grid: 72 variants:
  - timeframe 1m or 5m;
  - swing size {3, 5, 8} at 1m and {2, 3, 5} at 5m;
  - reward:risk {1, 1.5, 2};
  - first entry at 09:35 or 10:00;
  - session-VWAP trend filter off or on (longs only above VWAP, shorts only
    below, a new rule added for this search).

  The core BOS/CHoCH logic is unchanged.
- Selection: rank in-sample by t-stat of net R per trade, among variants
  with at least 100 trades. The luck benchmark is the expected best t of 72
  no-edge variants, about 2.41.
- Holdout: the top 3 picks, unchanged, run once.
- An edge is claimed only if a variant beats 2.41 in-sample AND on the
  holdout has net R > 0 with a one-sided p < 0.05/3 (t > 2.13). Anything
  less is reported as no edge, however good the best row looks.

## 2026-10-02 — Variant search result, and pre-registered cross-ticker test

- Search result ([run 36948159041](https://github.com/hmacknak/Fundamentally-Different/actions/runs/36948159041)):
  **no edge under the pre-registered rule.**
  - The best in-sample variant was 5m, swing 3, 1:1 (136 trades, +0.213R,
    t 2.92). It beat the 2.41 luck benchmark.
  - On the holdout it made +0.167R over only 29 trades (t 1.15), which
    fails the t > 2.13 bar. The holdout has too few trades to settle it
    either way.
  - The 09:35 vs 10:00 entry-start dimension was inert: no setup completes
    before 10:00 at these swing sizes, so the effective grid was 36
    variants and the 2.41 benchmark was conservative.
- Next test, fixed before running (`playground/smc/confirm_smc.py`):
  - Run that one variant, unchanged, on QQQ, IWM and DIA over the same 5
    years. It was chosen on SPY alone, so this data is out-of-sample.
  - Pass only if pooled net R > 0 with a one-sided p < 0.05, using
    day-clustered t-stats because the ETFs are correlated, AND net R > 0
    on at least 2 of the 3 tickers.
  - Whatever the outcome, there will be no further re-tuning on these
    tickers. A pass would justify forward paper trading, not real money.
- Cross-ticker result ([run 36948445551](https://github.com/hmacknak/Fundamentally-Different/actions/runs/36948445551)):
  **NOT CONFIRMED.**
  - QQQ: 151 trades, -0.097R (t -1.44).
  - IWM: 157 trades, -0.018R (t -0.27).
  - DIA: 170 trades, +0.021R (t +0.30).
  - Pooled: 478 trades, -0.029R, day-clustered t -0.71, p 0.76. Positive
    on 1 of 3 tickers.
- Conclusion: the SPY 5m/swing-3/1:1 result is best explained as a lucky
  pick from the search. Across everything tested, this BOS/CHoCH-retest
  family shows no edge after costs on liquid US index ETFs. Per the
  pre-registration, there will be no re-tuning on these results. Any
  further work needs a new, separately pre-registered hypothesis.
