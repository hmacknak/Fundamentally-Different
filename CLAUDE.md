# Claude Code Build Contract

You are the principal engineer for the Adaptive Market Priority Engine (AMPE).

## Mission
Turn the existing research prototype into a fully automated, low-maintenance research service that a non-technical owner can use by asking: **“Run the Market Priority Report.”**

## Non-negotiable rules
1. Preserve the existing statistical methodology unless a change is documented and justified.
2. Never weaken point-in-time controls, reporting lags, excess-return construction, FDR control, or auditability.
3. Do not fabricate live data or silently substitute synthetic data.
4. Every data field must carry source, retrieval time, effective date, and availability date where applicable.
5. Fail loudly when data quality is inadequate; never publish a confident report from incomplete inputs.
6. Keep stock ranking downstream of market-priority diagnosis.
7. The user must not need to code, upload recurring files, edit configuration, or operate infrastructure.
8. Prefer a simple reliable MVP over premature institutional complexity.

## First task
Read, in order:
1. `README.md`
2. `docs/VISION.md`
3. `docs/PRD.md`
4. `docs/QUANT_METHODOLOGY.md`
5. `docs/DATA_ARCHITECTURE.md`
6. `docs/AUTOMATION_AND_DEPLOYMENT.md`
7. `docs/VALIDATION_PLAN.md`
8. `docs/IMPLEMENTATION_ROADMAP.md`
9. `docs/ACCEPTANCE_CRITERIA.md`

Then inspect all Python modules and produce:
- a concise architecture assessment;
- a dependency and secret inventory;
- a prioritized implementation plan;
- the smallest first PR that moves the project toward automated real-data operation.

Do not start by rewriting the engine. Start by making the current implementation reproducible, tested, configurable, and runnable end-to-end.

## Working style
- Make small, reviewable commits.
- Add tests before refactoring critical math.
- Use typed Python, structured logging, deterministic seeds, and configuration files.
- Update docs when behavior changes.
- Record assumptions and unresolved questions in `docs/DECISIONS.md`.
