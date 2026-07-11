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
