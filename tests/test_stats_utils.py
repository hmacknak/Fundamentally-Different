import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from amp.stats_utils import (
    bh_fdr,
    expanding_zscore,
    ols_with_tstats,
    pct_rank,
    quintile_spread,
    spearman_ic,
    winsorize_series,
)


def test_ols_matches_statsmodels():
    rng = np.random.default_rng(0)
    x = rng.normal(size=200)
    y = 2.0 + 3.0 * x + rng.normal(scale=0.5, size=200)
    res = ols_with_tstats(x, y)
    sm_res = sm.OLS(y, sm.add_constant(x)).fit()
    np.testing.assert_allclose(res["beta"], sm_res.params, rtol=1e-8)
    np.testing.assert_allclose(res["se"], sm_res.bse, rtol=1e-6)
    np.testing.assert_allclose(res["t"], sm_res.tvalues, rtol=1e-6)
    np.testing.assert_allclose(res["p"], sm_res.pvalues, rtol=1e-6)


def test_ols_drops_nan_rows():
    x = np.array([1.0, 2.0, np.nan, 4.0, 5.0, 6.0])
    y = np.array([2.0, 4.0, 5.0, 8.0, 10.0, 12.0])
    res = ols_with_tstats(x, y)
    assert res["n"] == 5


def test_ols_returns_none_when_insufficient_dof():
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0, 3.0])
    assert ols_with_tstats(x, y) is None


def test_bh_fdr_is_monotonic_and_bounded():
    p = np.array([0.001, 0.01, 0.02, 0.04, 0.5, 0.9])
    q = bh_fdr(p)
    order = np.argsort(p)
    assert np.all(np.diff(q[order]) >= -1e-12)
    assert np.all((q >= 0) & (q <= 1))


def test_bh_fdr_nan_passthrough():
    p = np.array([0.01, np.nan, 0.03])
    q = bh_fdr(p)
    assert np.isnan(q[1])
    assert not np.isnan(q[0])
    assert not np.isnan(q[2])


def test_bh_fdr_empty_input():
    q = bh_fdr(np.array([]))
    assert len(q) == 0


def test_winsorize_series_clips_tails():
    s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 100])
    w = winsorize_series(s, lo=0.1, hi=0.9)
    assert w.max() < 100


def test_winsorize_series_short_series_unchanged():
    s = pd.Series([1.0, 2.0, 3.0])
    w = winsorize_series(s)
    pd.testing.assert_series_equal(w, s)


def test_pct_rank_range():
    s = pd.Series([3, 1, 2])
    r = pct_rank(s)
    assert r.min() > 0 and r.max() <= 1.0


def test_spearman_ic_perfect_positive_relationship():
    f = pd.Series(range(20))
    r = pd.Series(range(20))
    ic, n = spearman_ic(f, r)
    assert ic == pytest.approx(1.0)
    assert n == 20


def test_spearman_ic_insufficient_n_returns_nan():
    f = pd.Series(range(5))
    r = pd.Series(range(5))
    ic, n = spearman_ic(f, r, min_n=10)
    assert np.isnan(ic)
    assert n == 5


def test_quintile_spread_positive_relationship():
    f = pd.Series(range(100))
    r = pd.Series(range(100))
    spread = quintile_spread(f, r)
    assert spread > 0


def test_expanding_zscore_has_no_lookahead():
    s = pd.Series(np.arange(1, 21, dtype=float))
    full = expanding_zscore(s, min_periods=8)
    partial = expanding_zscore(s.iloc[:15], min_periods=8)
    pd.testing.assert_series_equal(full.iloc[:15], partial, check_names=False)
