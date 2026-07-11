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


def _bulk_upsert(session: Session, model, rows: list[dict], index_elements: list[str],
                 update_columns: list[str], chunk_size: int = 500) -> int:
    """One INSERT ... ON CONFLICT DO UPDATE per chunk, instead of a
    query-then-insert round trip per row. The per-row version was fine
    against local SQLite in tests but made a full historical backfill against
    a real remote database (network round trip per row) impractically slow —
    caught on the first live ingestion run."""
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as insert_stmt
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as insert_stmt
    else:
        raise NotImplementedError(f"bulk upsert not implemented for dialect {dialect!r}")

    total = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        stmt = insert_stmt(model).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=index_elements,
            set_={c: getattr(stmt.excluded, c) for c in update_columns},
        )
        session.execute(stmt)
        total += len(chunk)
    return total


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
        now = dt.datetime.now(dt.timezone.utc)
        rows = [
            {"ticker": r["ticker"], "date": pd.Timestamp(r["date"]).date(),
             "adj_close": float(r["adj_close"]),
             "volume": float(r["volume"]) if pd.notna(r.get("volume")) else None,
             "provider": provider, "retrieved_at": now, "raw_payload_hash": payload_hash}
            for _, r in prices.iterrows()
        ]
        n = _bulk_upsert(session, PricesDaily, rows, index_elements=["ticker", "date"],
                         update_columns=["adj_close", "volume", "provider", "retrieved_at",
                                         "raw_payload_hash"])
        session.commit()
        _finish_run(session, run_id, n, warnings, "succeeded")
        return IngestionResult(run_id, "prices", provider, n, warnings, "succeeded")
    except Exception as e:
        session.rollback()
        _finish_run(session, run_id, 0, warnings, "failed", str(e))
        return IngestionResult(run_id, "prices", provider, 0, warnings, "failed", str(e))


def ingest_macro(session: Session, macro: pd.DataFrame, provider: str) -> IngestionResult:
    run_id = _start_run(session, "macro", provider)
    payload_hash = _hash_frame(macro)
    warnings: list[str] = []
    try:
        now = dt.datetime.now(dt.timezone.utc)
        series_cols = [c for c in macro.columns if c != "date"]
        rows = []
        for _, r in macro.iterrows():
            obs_date = pd.Timestamp(r["date"]).date()
            for col in series_cols:
                val = r[col]
                if pd.isna(val):
                    continue
                rows.append({"series_name": col, "observation_date": obs_date,
                            "provider": provider, "value": float(val),
                            "retrieved_at": now, "raw_payload_hash": payload_hash})
        n = _bulk_upsert(session, MacroObservation, rows,
                         index_elements=["series_name", "observation_date", "provider"],
                         update_columns=["value", "retrieved_at", "raw_payload_hash"])
        session.commit()
        _finish_run(session, run_id, n, warnings, "succeeded")
        return IngestionResult(run_id, "macro", provider, n, warnings, "succeeded")
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
        now = dt.datetime.now(dt.timezone.utc)
        rows = []
        for _, r in fundamentals.iterrows():
            period_end = pd.Timestamp(r["date"]).date()
            availability = period_end + dt.timedelta(days=availability_lag_days)
            row = {f: (float(r[f]) if f in r and pd.notna(r[f]) else None)
                  for f in FUNDAMENTALS_FIELDS}
            row.update({
                "ticker": r["ticker"], "period_end_date": period_end, "provider": provider,
                "availability_date": availability,
                "sector": r["sector"] if "sector" in r and pd.notna(r.get("sector")) else None,
                "retrieved_at": now, "raw_payload_hash": payload_hash,
            })
            rows.append(row)
        n = _bulk_upsert(session, FundamentalsReported, rows,
                         index_elements=["ticker", "period_end_date", "provider"],
                         update_columns=[*FUNDAMENTALS_FIELDS, "availability_date", "sector",
                                         "retrieved_at", "raw_payload_hash"])
        session.commit()
        _finish_run(session, run_id, n, warnings, "succeeded")
        return IngestionResult(run_id, "fundamentals", provider, n, warnings, "succeeded")
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
