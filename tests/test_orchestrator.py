import datetime as dt
import os

import pandas as pd
import pytest

from amp import synth
from service.db import get_session_factory, init_db
from service.db.models import FactorScore, PublishedReport, ResearchRun
from service.ingestion import ingest_fundamentals, ingest_macro, ingest_prices
from service.orchestrator import run_market_priority_report


@pytest.fixture
def session_factory():
    engine = init_db("sqlite:///:memory:")
    return get_session_factory(engine)


def _ingest_synthetic_dataset(session, tmp_path, seed=42, n_tickers=25):
    synth_dir = str(tmp_path / "synthetic_inputs")
    # Shorter window than synth.generate's default (2017-2026) keeps per-row-upsert
    # ingestion fast in tests while still covering >1y lookback + rebalances.
    p_path, f_path, m_path = synth.generate(synth_dir, n_tickers=n_tickers, seed=seed,
                                            start="2020-01-01", end="2022-06-01")
    prices = pd.read_csv(p_path)
    fundamentals = pd.read_csv(f_path)
    macro = pd.read_csv(m_path)

    ingest_prices(session, prices, provider="yfinance")
    ingest_macro(session, macro, provider="fred+yfinance")
    ingest_fundamentals(session, fundamentals, provider="fmp", availability_lag_days=1)

    universe = sorted(prices["ticker"].unique())
    as_of = pd.Timestamp(prices["date"].max()).date()
    return universe, as_of


def test_run_market_priority_report_publishes_when_data_is_sufficient(session_factory, tmp_path):
    with session_factory() as s:
        universe, as_of = _ingest_synthetic_dataset(s, tmp_path)
        output_dir = str(tmp_path / "out")

        result = run_market_priority_report(
            s, universe, as_of, output_dir,
            gate_kwargs={"min_price_coverage": 0.5, "min_fundamentals_coverage": 0.5,
                        "max_price_staleness_days": 5, "max_macro_staleness_days": 45},
        )

        assert result.status == "published", result.gate.failures if result.gate else result.message
        assert result.report_id is not None
        assert os.path.exists(os.path.join(output_dir, "market_priority_report.md"))

        published = s.query(PublishedReport).filter_by(report_id=result.report_id).one()
        assert published.status == "valid"
        run = s.query(ResearchRun).filter_by(id=published.research_run_id).one()
        assert run.status == "valid"
        assert s.query(FactorScore).filter_by(research_run_id=run.id).count() > 0


def test_run_market_priority_report_blocks_publication_on_failed_gate(session_factory, tmp_path):
    with session_factory() as s:
        output_dir = str(tmp_path / "out_blocked")
        # empty database: gate must fail (no prices/macro/fundamentals at all)
        result = run_market_priority_report(s, ["AAA", "BBB"], dt.date(2024, 1, 1), output_dir)

        assert result.status == "blocked"
        assert result.report_id is None
        assert len(result.gate.failures) > 0
        assert os.path.exists(os.path.join(output_dir, "data_quality_failure.md"))
        assert s.query(PublishedReport).count() == 0


def test_blocked_run_does_not_touch_a_prior_published_report(session_factory, tmp_path):
    with session_factory() as s:
        universe, as_of = _ingest_synthetic_dataset(s, tmp_path)
        good_dir = str(tmp_path / "good")
        first = run_market_priority_report(
            s, universe, as_of, good_dir,
            gate_kwargs={"min_price_coverage": 0.5, "min_fundamentals_coverage": 0.5},
        )
        assert first.status == "published"
        published_before = s.query(PublishedReport).count()

        bad_dir = str(tmp_path / "bad")
        second = run_market_priority_report(s, ["NOPE"], as_of, bad_dir)
        assert second.status == "blocked"

        # the earlier published report/output is untouched
        assert s.query(PublishedReport).count() == published_before
        assert os.path.exists(os.path.join(good_dir, "market_priority_report.md"))
