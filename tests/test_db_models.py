import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from service.db import get_session_factory, init_db
from service.db.models import (
    FactorScore,
    FundamentalsReported,
    InteractionTest,
    MacroObservation,
    PricesDaily,
    PublishedReport,
    ResearchRun,
    SecurityMaster,
    SecurityRank,
)


@pytest.fixture
def session_factory():
    engine = init_db("sqlite:///:memory:")
    return get_session_factory(engine)


def test_init_db_creates_all_expected_tables():
    engine = init_db("sqlite:///:memory:")
    tables = set(engine.dialect.get_table_names(engine.connect()))
    expected = {
        "security_master", "universe_membership", "prices_daily",
        "fundamentals_reported", "macro_observations", "data_ingestion_runs",
        "research_runs", "factor_scores", "priority_scores", "interaction_tests",
        "security_ranks", "published_reports",
    }
    assert expected.issubset(tables)


def test_prices_daily_rejects_duplicate_ticker_date(session_factory):
    with session_factory() as s:
        s.add(PricesDaily(ticker="AAA", date=dt.date(2020, 1, 1), adj_close=10.0,
                          volume=100, provider="yfinance"))
        s.commit()
        s.add(PricesDaily(ticker="AAA", date=dt.date(2020, 1, 1), adj_close=11.0,
                          volume=110, provider="yfinance"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_security_master_ticker_is_unique(session_factory):
    with session_factory() as s:
        s.add(SecurityMaster(ticker="AAA"))
        s.commit()
        s.add(SecurityMaster(ticker="AAA"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_fundamentals_reported_round_trip(session_factory):
    with session_factory() as s:
        s.add(FundamentalsReported(
            ticker="AAA", period_end_date=dt.date(2020, 3, 31),
            availability_date=dt.date(2020, 5, 30),
            fcf_yield=0.05, debt_to_equity=0.8, provider="fmp",
        ))
        s.commit()
        row = s.query(FundamentalsReported).filter_by(ticker="AAA").one()
        assert row.fcf_yield == pytest.approx(0.05)
        assert row.availability_date == dt.date(2020, 5, 30)


def test_macro_observation_round_trip(session_factory):
    with session_factory() as s:
        s.add(MacroObservation(series_name="credit_spread", observation_date=dt.date(2020, 1, 31),
                               value=1.6, provider="fred"))
        s.commit()
        row = s.query(MacroObservation).filter_by(series_name="credit_spread").one()
        assert row.value == pytest.approx(1.6)


def test_research_run_cascades_to_factor_and_priority_children(session_factory):
    with session_factory() as s:
        run = ResearchRun(run_id="run-1", as_of_date=dt.date(2020, 3, 31), config_json="{}")
        s.add(run)
        s.commit()

        s.add(FactorScore(research_run_id=run.id, date=dt.date(2020, 3, 31),
                          factor="fcf_yield", ic=0.1, n_stocks=50))
        s.add(InteractionTest(research_run_id=run.id, factor="fcf_yield",
                              macro_state="credit_spread_z", interaction_beta=0.01,
                              t_stat=2.0, p_value=0.05, q_value=0.08,
                              significant_fdr=True, n_periods=20, n_tests_in_family=10))
        s.add(SecurityRank(research_run_id=run.id, as_of_date=dt.date(2020, 3, 31),
                           ticker="AAA", rank=1, composite_score=0.9))
        s.commit()

        loaded = s.query(ResearchRun).filter_by(run_id="run-1").one()
        assert len(loaded.factor_scores) == 1
        assert len(loaded.interaction_tests) == 1
        assert len(loaded.security_ranks) == 1


def test_published_report_references_research_run(session_factory):
    with session_factory() as s:
        run = ResearchRun(run_id="run-2", as_of_date=dt.date(2020, 3, 31), config_json="{}")
        s.add(run)
        s.commit()
        s.add(PublishedReport(report_id="rep-1", research_run_id=run.id,
                              as_of_date=dt.date(2020, 3, 31), status="valid"))
        s.commit()
        rep = s.query(PublishedReport).filter_by(report_id="rep-1").one()
        assert rep.research_run_id == run.id
