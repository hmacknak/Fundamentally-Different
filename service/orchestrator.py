"""Orchestrator: "Run the Market Priority Report," end to end.

Ties the data-quality gate -> the research engine -> DB persistence, per
docs/PRD.md's primary command and docs/AUTOMATION_AND_DEPLOYMENT.md's
failure-handling rules: never overwrite the last valid published report
with a failed run, and publish a failure summary (not a report) when the
gate fails.

Fetching live data (network calls, needs FMP/FRED credentials) is a
separate step (see run_ingestion.py) — this module only reads whatever is
already in the database, so it is fully unit-testable without network
access or API keys.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import subprocess
import tempfile
import uuid

import pandas as pd
from sqlalchemy.orm import Session

from adaptive_market_priority_engine import main as run_engine
from service.db.models import (
    FactorScore,
    FundamentalsReported,
    InteractionTest,
    MacroObservation,
    PricesDaily,
    PriorityScore,
    PublishedReport,
    ResearchRun,
    SecurityRank,
)
from service.ingestion import GateResult, check_data_quality_gate

FUNDAMENTALS_EXPORT_COLUMNS = [
    "fcf_yield", "debt_to_equity", "roe", "revenue_growth", "pe", "ev_ebitda",
    "dividend_yield", "interest_coverage", "gross_margin", "operating_margin",
    "free_cash_flow_margin", "eps_revision", "shares_dilution", "sector",
]


@dataclasses.dataclass
class OrchestrationResult:
    status: str  # "published" | "blocked" | "failed"
    report_id: str | None
    as_of_date: dt.date | None
    gate: GateResult | None
    message: str
    output_dir: str | None = None


def _export_prices_csv(session: Session, universe: list[str], path: str) -> None:
    rows = session.query(PricesDaily).filter(PricesDaily.ticker.in_(universe)).all()
    df = pd.DataFrame([{"date": r.date, "ticker": r.ticker, "adj_close": r.adj_close,
                        "volume": r.volume} for r in rows])
    if df.empty:
        df = pd.DataFrame(columns=["date", "ticker", "adj_close", "volume"])
    df.to_csv(path, index=False)


def _export_macro_csv(session: Session, path: str) -> None:
    rows = session.query(MacroObservation).all()
    if not rows:
        pd.DataFrame(columns=["date"]).to_csv(path, index=False)
        return
    long_df = pd.DataFrame([{"date": r.observation_date, "series": r.series_name,
                             "value": r.value} for r in rows])
    wide = (long_df.pivot_table(index="date", columns="series", values="value", aggfunc="last")
           .reset_index())
    wide.to_csv(path, index=False)


def _export_fundamentals_csv(session: Session, universe: list[str], path: str) -> None:
    rows = (session.query(FundamentalsReported)
           .filter(FundamentalsReported.ticker.in_(universe)).all())
    out = []
    for r in rows:
        row = {"date": r.period_end_date, "ticker": r.ticker}
        for c in FUNDAMENTALS_EXPORT_COLUMNS:
            row[c] = getattr(r, c)
        out.append(row)
    df = pd.DataFrame(out) if out else pd.DataFrame(
        columns=["date", "ticker", *FUNDAMENTALS_EXPORT_COLUMNS])
    df.to_csv(path, index=False)


def _write_failure_summary(output_dir: str, gate: GateResult) -> None:
    os.makedirs(output_dir, exist_ok=True)
    lines = ["# Market Priority Report — publication blocked", "",
             "The data-quality gate failed; no report was published. "
             "The prior valid report (if any) is untouched.", "", "## Failures"]
    lines += [f"- {f}" for f in gate.failures]
    if gate.warnings:
        lines += ["", "## Warnings"] + [f"- {w}" for w in gate.warnings]
    with open(os.path.join(output_dir, "data_quality_failure.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _git_commit_sha() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5, check=True)
        return out.stdout.strip()
    except Exception:
        return None


def _persist_research_run(session: Session, output_dir: str, config: dict,
                          gate: GateResult) -> tuple[int, dt.date]:
    rolled = pd.read_csv(os.path.join(output_dir, "factor_scores.csv"), parse_dates=["date"])
    pscores = pd.read_csv(os.path.join(output_dir, "priority_scores.csv"), parse_dates=["date"])
    try:
        itests = pd.read_csv(os.path.join(output_dir, "interaction_tests.csv"))
    except pd.errors.EmptyDataError:
        # too few rebalance periods for any factor x macro pair to reach min_obs — a
        # valid outcome (e.g. early in a deployment's life), not a persistence error.
        itests = pd.DataFrame()
    ranks = pd.read_csv(os.path.join(output_dir, "latest_stock_ranks.csv"), parse_dates=["as_of_date"])

    as_of_date = rolled["date"].max().date()

    run = ResearchRun(
        run_id=str(uuid.uuid4()), as_of_date=as_of_date, config_json=json.dumps(config),
        code_commit_sha=_git_commit_sha(),
        warnings_json=json.dumps(gate.warnings), status="valid",
    )
    session.add(run)
    session.flush()

    for _, r in rolled.iterrows():
        session.add(FactorScore(
            research_run_id=run.id, date=r["date"].date(), factor=r["factor"],
            ic=_none_if_nan(r.get("ic")), spread=_none_if_nan(r.get("spread")),
            payoff_slope=_none_if_nan(r.get("payoff_slope")),
            n_stocks=_none_if_nan(r.get("n_stocks")),
            rolling_ic=_none_if_nan(r.get("rolling_ic")),
            rolling_ic_se=_none_if_nan(r.get("rolling_ic_se")),
            rolling_ic_t=_none_if_nan(r.get("rolling_ic_t")),
            rolling_spread=_none_if_nan(r.get("rolling_spread")),
            hit_rate=_none_if_nan(r.get("hit_rate")),
            strengthening_1p=_none_if_nan(r.get("strengthening_1p")),
            strengthening_4p=_none_if_nan(r.get("strengthening_4p")),
        ))
    for _, r in pscores.iterrows():
        session.add(PriorityScore(
            research_run_id=run.id, date=r["date"].date(), priority=r["priority"],
            priority_score=float(r["priority_score"]),
            priority_spread=_none_if_nan(r.get("priority_spread")),
            strengthening=_none_if_nan(r.get("strengthening")),
            n_members_scored=int(r["n_members_scored"]),
            n_members_defined=int(r["n_members_defined"]),
            priority_z=_none_if_nan(r.get("priority_z")),
        ))
    for _, r in itests.iterrows():
        session.add(InteractionTest(
            research_run_id=run.id, factor=r["factor"], macro_state=r["macro_state"],
            interaction_beta=float(r["interaction_beta"]), t_stat=float(r["t_stat"]),
            p_value=float(r["p_value"]), q_value=float(r["q_value"]),
            significant_fdr=bool(r["significant_fdr"]), n_periods=int(r["n_periods"]),
            n_tests_in_family=int(r["n_tests_in_family"]),
            base_payoff=_none_if_nan(r.get("base_payoff")),
        ))
    for _, r in ranks.iterrows():
        session.add(SecurityRank(
            research_run_id=run.id, as_of_date=r["as_of_date"].date(), ticker=r["ticker"],
            rank=int(r["rank"]), composite_score=float(r["composite_score"]),
        ))
    session.commit()
    return run.id, as_of_date


def _none_if_nan(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def run_market_priority_report(
    session: Session, universe: list[str], as_of: dt.date, output_dir: str, *,
    rebalance: str = "Q", holding_months: int = 3, rolling_windows: int = 8,
    top_n: int = 20, fundamental_lag_days: int = 60, fdr: float = 0.10,
    gate_kwargs: dict | None = None,
) -> OrchestrationResult:
    gate = check_data_quality_gate(session, universe, as_of, **(gate_kwargs or {}))
    if not gate.passed:
        _write_failure_summary(output_dir, gate)
        return OrchestrationResult(status="blocked", report_id=None, as_of_date=as_of, gate=gate,
                                   message="Data-quality gate failed; publication blocked.",
                                   output_dir=output_dir)

    config = {"rebalance": rebalance, "holding_months": holding_months,
             "rolling_windows": rolling_windows, "top_n": top_n,
             "fundamental_lag_days": fundamental_lag_days, "fdr": fdr}

    with tempfile.TemporaryDirectory() as tmp:
        prices_path = os.path.join(tmp, "prices.csv")
        fundamentals_path = os.path.join(tmp, "fundamentals.csv")
        macro_path = os.path.join(tmp, "macro.csv")
        _export_prices_csv(session, universe, prices_path)
        _export_fundamentals_csv(session, universe, fundamentals_path)
        _export_macro_csv(session, macro_path)

        rc = run_engine([
            "--prices", prices_path, "--fundamentals", fundamentals_path,
            "--macro", macro_path, "--output", output_dir,
            "--rebalance", rebalance, "--holding-months", str(holding_months),
            "--rolling-windows", str(rolling_windows), "--top-n", str(top_n),
            "--fundamental-lag-days", str(fundamental_lag_days), "--fdr", str(fdr),
        ])

    if rc != 0:
        return OrchestrationResult(status="failed", report_id=None, as_of_date=as_of, gate=gate,
                                   message="Engine run failed; prior published report untouched.",
                                   output_dir=output_dir)

    research_run_id, engine_as_of = _persist_research_run(session, output_dir, config, gate)
    report_id = str(uuid.uuid4())
    session.add(PublishedReport(
        report_id=report_id, research_run_id=research_run_id, as_of_date=engine_as_of,
        status="valid",
        markdown_path=os.path.join(output_dir, "market_priority_report.md"),
        json_path=os.path.join(output_dir, "audit_trail.json"),
        audit_path=os.path.join(output_dir, "data_quality_report.md"),
    ))
    session.commit()
    return OrchestrationResult(status="published", report_id=report_id, as_of_date=engine_as_of,
                               gate=gate, message="Report published.", output_dir=output_dir)
