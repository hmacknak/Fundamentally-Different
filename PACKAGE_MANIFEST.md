# Package Manifest

## Reference implementation (preserved as-is; see docs/DECISIONS.md for the
## small syntax/dead-code fixes applied)
- `adaptive_market_priority_engine.py`
- `amp/` research modules
- `data_adapters.py`
- `output/` sample synthetic outputs

## Build guidance
- `CLAUDE.md`
- `START_HERE_FOR_CLAUDE.md`
- `docs/VISION.md`
- `docs/PRD.md`
- `docs/QUANT_METHODOLOGY.md`
- `docs/DATA_ARCHITECTURE.md`
- `docs/AUTOMATION_AND_DEPLOYMENT.md`
- `docs/VALIDATION_PLAN.md`
- `docs/AI_INTERFACE.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `docs/ACCEPTANCE_CRITERIA.md`
- `docs/CODING_STANDARDS.md`
- `docs/DECISIONS.md`
- `.github/workflows/ci.yml`
- `requirements.txt`
- `.gitignore`
- `config/example.env`

## Phase 0/1 additions (this build)
- `tests/` — 73 pytest tests (stats, features, interactions, priorities,
  validation, DB models, ingestion, orchestrator, engine golden/control tests)
- `pytest.ini`
- `service/config.py` — env-based configuration, no hard-coded secrets
- `service/db/` — SQLAlchemy schema (docs/DATA_ARCHITECTURE.md's 12 tables)
  and session/engine setup (SQLite by default)
- `service/providers/` — tested vendor-mapping logic (FRED, yfinance, FMP)
  used by `data_adapters.py`
- `service/ingestion.py` — loads provider data into the DB with lineage;
  the data-quality publication gate
- `service/orchestrator.py` — ties gate -> engine -> DB persistence -> report
- `service/universe.py` — default universe (full S&P 500, 503 tickers)
- `run_ingestion.py`, `run_report.py` — the two CLI entrypoints
- `.github/workflows/ingest.yml`, `publish-report.yml` — scheduling scaffold
  (inert until `DATABASE_URL`/`FMP_API_KEY` secrets are added; see
  docs/DECISIONS.md)
