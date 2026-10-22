"""Tests for the pre-registered order-flow test (playground/orderflow)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "playground", "orderflow"))
import orderflow_test as of


def minutes(days=60, seed=0, momentum=0.0):
    """1m bars; with momentum > 0 each 15-minute block drifts in the
    direction of the previous block's net move."""
    rng = np.random.default_rng(seed)
    frames, px = [], 400.0
    for d in pd.bdate_range("2024-01-02", periods=days):
        idx = pd.date_range(pd.Timestamp(f"{d:%Y-%m-%d} 09:30", tz="America/New_York"),
                            periods=390, freq="1min")
        steps = rng.normal(0, 0.05, 390)
        for b in range(1, 26):
            prev = steps[(b - 1) * 15:b * 15].sum()
            steps[b * 15:(b + 1) * 15] += momentum * np.sign(prev) / 15
        c = px + np.cumsum(steps)
        o = np.r_[px, c[:-1]]
        frames.append(pd.DataFrame({"open": o, "close": c,
                                    "high": np.maximum(o, c) + 0.01,
                                    "low": np.minimum(o, c) - 0.01,
                                    "volume": rng.integers(1000, 5000, 390).astype(float)},
                                   index=idx))
        px = c[-1]
    return pd.concat(frames)


def test_bvc_is_causal_and_bounded():
    m = minutes(5, seed=1)
    d1 = of.bvc_delta(m)
    m2 = m.copy()
    m2.iloc[-1, m2.columns.get_loc("close")] += 50  # change only the last bar
    d2 = of.bvc_delta(m2)
    pd.testing.assert_series_equal(d1.iloc[:-1], d2.iloc[:-1])
    assert (d1.abs() <= m["volume"] + 1e-9).all()
    first = m.index.normalize() != np.r_[pd.NaT, m.index.normalize()[:-1]]
    assert (d1[first] == 0).all()


def test_trade_windows_are_non_overlapping_and_in_session():
    m = minutes(3, seed=2)
    tr = of.trades(m)
    flow = tr[tr["hyp"] == "FLOW"]
    assert set(flow["time"]) <= set(of.CHECKPOINTS)
    assert flow.groupby("day").size().max() == len(of.CHECKPOINTS)


def test_planted_flow_momentum_is_detected_and_null_is_not():
    strong = of.trades(minutes(120, seed=3, momentum=0.6))
    null = of.trades(minutes(120, seed=4))
    _, t_strong, _ = of.ef.nw_t(of.daily_series(strong, "FLOW", "gross").to_numpy())
    _, t_null, _ = of.ef.nw_t(of.daily_series(null, "FLOW", "gross").to_numpy())
    assert t_strong > 4 and abs(t_null) < 3


def test_cli_end_to_end(tmp_path):
    for i, tk in enumerate(of.TICKERS):
        minutes(40, seed=10 + i).rename_axis("timestamp").to_csv(tmp_path / f"{tk}.csv")
    out = tmp_path / "o"
    assert of.main(["--intraday-dir", str(tmp_path), "--out", str(out)]) == 0
    assert "EDGES" in (out / "report.md").read_text()
