"""Tests for the pre-registered anomaly family (playground/edges)."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "playground", "edges"))
import edge_family as ef


def daily(n=4000, seed=0, tom_bp=0.0, ovn_bp=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2005-01-03", periods=n)
    month = idx.to_period("M")
    s = pd.Series(1, index=idx)
    pos = s.groupby(month).cumsum()
    left = s[::-1].groupby(month[::-1]).cumsum()[::-1]
    tom = ((left == 1) | (pos <= 3)).to_numpy()
    on = rng.normal(ovn_bp / 1e4, 0.004, n)
    intra = rng.normal(0, 0.008, n) + np.where(tom, tom_bp / 1e4, 0)
    close, opens, px = [], [], 100.0
    for i in range(n):
        o = px * (1 + on[i])
        c = o * (1 + intra[i])
        opens.append(o)
        close.append(c)
        px = c
    o, c = np.array(opens), np.array(close)
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.003, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.003, n)))
    return pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c}, index=idx)


def test_nw_t_recovers_planted_dummy_effect():
    rng = np.random.default_rng(1)
    x = (rng.random(5000) < 0.2).astype(float)
    y = rng.normal(0, 1, 5000) + 0.3 * x
    b, t, n = ef.nw_t(y, x)
    assert b == pytest.approx(0.3, abs=0.08) and t > 5 and n == 5000


def test_tom_flags_last_day_and_first_three():
    d = daily(60)
    f = ef.h_tom(d)
    jan = f[f.index.month == 1]
    assert jan["active"].iloc[:3].all() and not jan["active"].iloc[3]
    assert f[f.index.month == 1]["active"].iloc[-1]


def test_planted_tom_detected_null_not():
    _, t_planted, _ = ef.effect(ef.h_tom(daily(seed=2, tom_bp=25)))
    _, t_null, _ = ef.effect(ef.h_tom(daily(seed=3)))
    assert t_planted > 3 and abs(t_null) < 3


def test_overnight_effect_charges_two_sides():
    d = daily(500, seed=4, ovn_bp=0)
    f = ef.h_ovn(d)
    expected = d["open"] / d["close"].shift(1) - 1 - 2 * ef.COST - (d["close"] / d["open"] - 1)
    pd.testing.assert_series_equal(f["y"], expected, check_names=False)


def test_ibs_signal_uses_only_prior_bar():
    d = daily(300, seed=5)
    f1 = ef.h_ibs(d)
    d2 = d.copy()
    d2.iloc[-1, d2.columns.get_loc("close")] = d2["low"].iloc[-1]  # change today only
    f2 = ef.h_ibs(d2)
    assert f1["active"].iloc[-1] == f2["active"].iloc[-1]


def test_end_to_end_reports_verdicts(tmp_path):
    dd = tmp_path / "daily"
    dd.mkdir()
    for i, tk in enumerate(ef.TICKERS):
        daily(4500, seed=10 + i, tom_bp=30).to_csv(dd / f"{tk}.csv")
    out = tmp_path / "edges"
    assert ef.main(["--daily-dir", str(dd), "--out", str(out)]) == 0
    v = pd.read_csv(out / "verdicts.csv").set_index("hyp")
    assert bool(v.loc["TOM", "EDGE"]) is True
    assert bool(v.loc["OVN", "EDGE"]) is False
