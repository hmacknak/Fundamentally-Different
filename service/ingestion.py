"""Ingestion pipeline: load provider-fetched data into the database with
lineage, and gate publication on freshness/coverage checks.

Per docs/VALIDATION_PLAN.md's publication gate and CLAUDE.md rule #5
("fail loudly when data quality is inadequate; never publish a confident
report from incomplete inputs"), check_data_quality_gate returns a result
the orchestrator must honor: a failing gate blocks publication rather than
producing a report from incomplete inputs.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import uuid

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from service.db.models import (
    DataIngestionRun,
    FundamentalsReported,
    MacroObservation,
    PricesDaily,
)

FUNDAMENTALS_FIELDS = [
    "fcf_yield", "debt_to_equity", "roe", "revenue_growth", "pe", "ev_ebitda",
    "dividend_yield", "interest_coverage", "gross_margin", "operating_margin",
    "free_cash_flow_margin", "eps_revision", "shares_dilution",
]


@dataclasses.dataclass
class IngestionResult:
    run_id: str
    domain: str
    provider: str
    rows_ingested: int
    warnings: list
    status: str  # "succeeded" | "failed"
    error_message: str | None = None


@dataclasses.dataclass
class GateResult:
    passed: bool
    failures: list
    warnings: list


def _hash_frame(df: pd.DataFrame) -> str:
    if df.empty:
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()


def _upsert(session: Session, model, natural_key: dict, values: dict) -> None:
    existing = session.query(model).filter_by(**natural_key).one_or_none()
    if existing is None:
        session.add(model(**{**natural_key, **values}))
    else:
        for k, v in values.items():
            setattr(existing, k, v)


def _start_run(session: Session, domain: str, provider: str) -> str:
    run = DataIngestionRun(run_id=str(uuid.uuid4()), domain=domain, provider=provider,
                           status="running")
    session.add(run)
    session.commit()  # persisted immediately so a later failure still leaves an audit row
    return run.run_id


def _finish_run(session: Session, run_id: str, rows: int, warnings: list, status: str,
                error_message: str | None = None) -> None:
    run = session.query(DataIngestionRun).filter_by(run_id=run_id).one()
    run.rows_ingested = rows
    run.status = status
    run.warnings_json = json.dumps(warnings)
    run.error_message = error_message
    run.finished_at = dt.datetime.now(dt.timezone.utc)
    session.commit()


def ingest_prices(session: Session, prices: pd.DataFrame, provider: str) -> IngestionResult:
    run_id = _start_run(session, "prices", provider)
    payload_hash = _hash_frame(prices)
    warnings: list[str] = []
    try:
        rows = 0
        now = dt.datetime.now(dt.timezone.utc)
        for _, r in prices.iterrows():
            _upsert(
                session, PricesDaily,
                {"ticker": r["ticker"], "date": pd.Timestamp(r["date"]).date()},
                {"adj_close": float(r["adj_close"]),
                 "volume": float(r["volume"]) if pd.notna(r.get("volume")) else None,
                 "provider": provider, "retrieved_at": now, "raw_payload_hash": payload_hash},
            )
            rows += 1
        session.commit()
        _finish_run(session, run_id, rows, warnings, "succeeded")
        return IngestionResult(run_id, "prices", provider, rows, warnings, "succeeded")
    except Exception as e:
        session.rollback()
        _finish_run(session, run_id, 0, warnings, "failed", str(e))
        return IngestionResult(run_id, "prices", provider, 0, warnings, "failed", str(e))


def ingest_macro(session: Session, macro: pd.DataFrame, provider: str) -> IngestionResult:
    run_id = _start_run(session, "macro", provider)
    payload_hash = _hash_frame(macro)
    warnings: list[str] = []
    try:
        rows = 0
        now = dt.datetime.now(dt.timezone.utc)
        series_cols = [c for c in macro.columns if c != "date"]
        for _, r in macro.iterrows():
            obs_date = pd.Timestamp(r["date"]).date()
            for col in series_cols:
                val = r[col]
                if pd.isna(val):
                    continue
                _upsert(
                    session, MacroObservation,
                    {"series_name": col, "observation_date": obs_date, "provider": provider},
                    {"value": float(val), "retrieved_at": now, "raw_payload_hash": payload_hash},
                )
                rows += 1
        session.commit()
        _finish_run(session, run_id, rows, warnings, "succeeded")
        return IngestionResult(run_id, "macro", provider, rows, warnings, "succeeded")
    except Exception as e:
        session.rollback()
        _finish_run(session, run_id, 0, warnings, "failed", str(e))
        return IngestionResult(run_id, "macro", provider, 0, warnings, "failed", str(e))


def ingest_fundamentals(session: Session, fundamentals: pd.DataFrame, provider: str,
                        availability_lag_days: int = 60) -> IngestionResult:
    """`availability_date` defaults to period_end_date + availability_lag_days when the
    provider doesn't supply a real filing/accepted date — the conservative-lag fallback
    docs/QUANT_METHODOLOGY.md requires when a true availability date is unavailable."""
    run_id = _start_run(session, "fundamentals", provider)
    payload_hash = _hash_frame(fundamentals)
    warnings: list[str] = []
    try:
        rows = 0
        now = dt.datetime.now(dt.timezone.utc)
        for _, r in fundamentals.iterrows():
            period_end = pd.Timestamp(r["date"]).date()
            availability = period_end + dt.timedelta(days=availability_lag_days)
            values = {f: (float(r[f]) if f in r and pd.notna(r[f]) else None)
                     for f in FUNDAMENTALS_FIELDS}
            values.update({
                "availability_date": availability,
                "sector": r["sector"] if "sector" in r and pd.notna(r.get("sector")) else None,
                "provider": provider, "retrieved_at": now, "raw_payload_hash": payload_hash,
            })
            _upsert(
                session, FundamentalsReported,
                {"ticker": r["ticker"], "period_end_date": period_end, "provider": provider},
                values,
            )
            rows += 1
        session.commit()
        _finish_run(session, run_id, rows, warnings, "succeeded")
        return IngestionResult(run_id, "fundamentals", provider, rows, warnings, "succeeded")
    except Exception as e:
        session.rollback()
        _finish_run(session, run_id, 0, warnings, "failed", str(e))
        return IngestionResult(run_id, "fundamentals", provider, 0, warnings, "failed", str(e))


def check_data_quality_gate(
    session: Session, universe: list[str], as_of: dt.date, *,
    max_price_staleness_days: int = 5,
    max_macro_staleness_days: int = 45,
    min_price_coverage: float = 0.6,
    min_fundamentals_coverage: float = 0.5,
    required_macro_series: tuple = ("credit_spread", "rate_10y", "vix", "benchmark_adj_close"),
) -> GateResult:
    """Fail loudly rather than publish from stale or thin data (ACCEPTANCE_CRITERIA.md:
    'Failed or stale data blocks publication')."""
    failures: list[str] = []
    warnings: list[str] = []

    latest_by_ticker = dict(
        session.query(PricesDaily.ticker, func.max(PricesDaily.date))
        .filter(PricesDaily.ticker.in_(universe))
        .group_by(PricesDaily.ticker).all()
    )
    coverage = len(latest_by_ticker) / len(universe) if universe else 0.0
    if coverage < min_price_coverage:
        failures.append(f"price coverage {coverage:.0%} < required {min_price_coverage:.0%}")
    if not latest_by_ticker:
        failures.append("no price data available for the universe")
    else:
        stale = [tk for tk, d in latest_by_ticker.items() if (as_of - d).days > max_price_staleness_days]
        if len(stale) == len(latest_by_ticker):
            failures.append(f"all covered tickers have prices older than "
                            f"{max_price_staleness_days} days")
        elif stale:
            warnings.append(f"{len(stale)} ticker(s) have prices older than "
                            f"{max_price_staleness_days} days")

    for series in required_macro_series:
        latest = (session.query(func.max(MacroObservation.observation_date))
                 .filter(MacroObservation.series_name == series).scalar())
        if latest is None:
            failures.append(f"macro series '{series}' has no observations")
        elif (as_of - latest).days > max_macro_staleness_days:
            failures.append(f"macro series '{series}' is stale: last observation {latest}")

    fund_tickers = {
        t for (t,) in session.query(FundamentalsReported.ticker)
        .filter(FundamentalsReported.ticker.in_(universe),
                FundamentalsReported.availability_date <= as_of)
        .distinct().all()
    }
    fcoverage = len(fund_tickers) / len(universe) if universe else 0.0
    if fcoverage < min_fundamentals_coverage:
        failures.append(f"fundamentals coverage {fcoverage:.0%} < "
                        f"required {min_fundamentals_coverage:.0%}")

    return GateResult(passed=(len(failures) == 0), failures=failures, warnings=warnings)
