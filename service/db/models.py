"""Database schema, per docs/DATA_ARCHITECTURE.md.

SQLite is the default store for the MVP (no hosted database account
required); the same models work unchanged against PostgreSQL by pointing
DATABASE_URL at it later (see service/config.py). Every ingested row and
every research run retains lineage: provider, retrieval time, source key,
and (for ingested data) a hash of the raw payload, per the data
architecture's lineage requirement.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class SecurityMaster(Base):
    __tablename__ = "security_master"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class UniverseMembership(Base):
    __tablename__ = "universe_membership"
    __table_args__ = (UniqueConstraint("universe_name", "ticker", "start_date",
                                        name="uq_universe_membership"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    universe_name: Mapped[str] = mapped_column(String, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)


class PricesDaily(Base):
    __tablename__ = "prices_daily"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_prices_daily_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    adj_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    source_key: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class FundamentalsReported(Base):
    __tablename__ = "fundamentals_reported"
    __table_args__ = (UniqueConstraint("ticker", "period_end_date", "provider",
                                        name="uq_fundamentals_ticker_period_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    period_end_date: Mapped[dt.date] = mapped_column(Date, index=True)
    filing_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    accepted_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    availability_date: Mapped[dt.date | None] = mapped_column(
        Date, nullable=True,
        doc="Date this observation may first enter a rebalance. Falls back to "
            "period_end_date + the engine's conservative lag when unknown.",
    )
    sector: Mapped[str | None] = mapped_column(String, nullable=True)

    fcf_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    ev_ebitda: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_cash_flow_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_revision: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares_dilution: Mapped[float | None] = mapped_column(Float, nullable=True)

    provider: Mapped[str] = mapped_column(String)
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    source_key: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class MacroObservation(Base):
    __tablename__ = "macro_observations"
    __table_args__ = (UniqueConstraint("series_name", "observation_date", "provider",
                                        name="uq_macro_series_date_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_name: Mapped[str] = mapped_column(String, index=True)
    observation_date: Mapped[dt.date] = mapped_column(Date, index=True)
    release_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    value: Mapped[float] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String)
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    source_key: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_payload_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class DataIngestionRun(Base):
    __tablename__ = "data_ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    domain: Mapped[str] = mapped_column(String)  # prices | fundamentals | macro | universe
    provider: Mapped[str] = mapped_column(String)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")  # running|succeeded|failed
    rows_ingested: Mapped[int] = mapped_column(Integer, default=0)
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date, index=True)
    config_json: Mapped[str] = mapped_column(Text)
    code_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    input_snapshot_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")  # running|valid|blocked|failed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)

    factor_scores: Mapped[list["FactorScore"]] = relationship(back_populates="research_run")
    priority_scores: Mapped[list["PriorityScore"]] = relationship(back_populates="research_run")
    interaction_tests: Mapped[list["InteractionTest"]] = relationship(back_populates="research_run")
    security_ranks: Mapped[list["SecurityRank"]] = relationship(back_populates="research_run")


class FactorScore(Base):
    __tablename__ = "factor_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey("research_runs.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    factor: Mapped[str] = mapped_column(String, index=True)
    ic: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    payoff_slope: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_stocks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rolling_ic: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_ic_se: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_ic_t: Mapped[float | None] = mapped_column(Float, nullable=True)
    rolling_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    strengthening_1p: Mapped[float | None] = mapped_column(Float, nullable=True)
    strengthening_4p: Mapped[float | None] = mapped_column(Float, nullable=True)

    research_run: Mapped[ResearchRun] = relationship(back_populates="factor_scores")


class PriorityScore(Base):
    __tablename__ = "priority_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey("research_runs.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    priority: Mapped[str] = mapped_column(String, index=True)
    priority_score: Mapped[float] = mapped_column(Float)
    priority_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    strengthening: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_members_scored: Mapped[int] = mapped_column(Integer)
    n_members_defined: Mapped[int] = mapped_column(Integer)
    priority_z: Mapped[float | None] = mapped_column(Float, nullable=True)

    research_run: Mapped[ResearchRun] = relationship(back_populates="priority_scores")


class InteractionTest(Base):
    __tablename__ = "interaction_tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey("research_runs.id"), index=True)
    factor: Mapped[str] = mapped_column(String, index=True)
    macro_state: Mapped[str] = mapped_column(String, index=True)
    interaction_beta: Mapped[float] = mapped_column(Float)
    t_stat: Mapped[float] = mapped_column(Float)
    p_value: Mapped[float] = mapped_column(Float)
    q_value: Mapped[float] = mapped_column(Float)
    significant_fdr: Mapped[bool] = mapped_column(Boolean)
    n_periods: Mapped[int] = mapped_column(Integer)
    n_tests_in_family: Mapped[int] = mapped_column(Integer)
    base_payoff: Mapped[float | None] = mapped_column(Float, nullable=True)

    research_run: Mapped[ResearchRun] = relationship(back_populates="interaction_tests")


class SecurityRank(Base):
    __tablename__ = "security_ranks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey("research_runs.id"), index=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    rank: Mapped[int] = mapped_column(Integer)
    composite_score: Mapped[float] = mapped_column(Float)

    research_run: Mapped[ResearchRun] = relationship(back_populates="security_ranks")


class PublishedReport(Base):
    __tablename__ = "published_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey("research_runs.id"), index=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String)  # valid|experimental|blocked
    published_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)
    markdown_path: Mapped[str | None] = mapped_column(String, nullable=True)
    json_path: Mapped[str | None] = mapped_column(String, nullable=True)
    audit_path: Mapped[str | None] = mapped_column(String, nullable=True)
