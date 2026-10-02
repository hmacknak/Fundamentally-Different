"""Tests for the playground intraday-momentum test (playground/momentum)."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "playground", "momentum"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "playground", "smc"))
import backtest_smc as bt
import intraday_momentum as im

MIN_PER_DAY = 390


def sessions(n: int, momentum: float, seed: int = 0, half_day: int | None = None
             ) -> pd.DataFrame:
    """1m bars. The 15:30-16:00 drift is `momentum` x sign(first-half-hour move)."""
    rng = np.random.default_rng(seed)
    frames, px = [], 400.0
    for i, d in enumerate(pd.bdate_range("2023-01-02", periods=n)):
        idx = pd.date_range(pd.Timestamp(f"{d:%Y-%m-%d} 09:30", tz=bt.ET),
                            periods=MIN_PER_DAY, freq="1min")
        steps = rng.normal(0, 0.05, MIN_PER_DAY)
        gap = rng.normal(0, 0.8)
        first = gap + steps[:30].sum()
        steps[360:] += momentum * np.sign(first) / 30
        close = px + gap + np.cumsum(steps)
        open_ = np.r_[px + gap, close[:-1]]
        df = pd.DataFrame({"open": open_, "close": close,
                           "high": np.maximum(open_, close) + 0.01,
                           "low": np.minimum(open_, close) - 0.01,
                           "volume": 100.0}, index=idx)
        if half_day is not None and i == half_day:
            df = df.iloc[:210]  # closes 13:00
        frames.append(df)
        px = df["close"].iloc[-1]
    return pd.concat(frames)


def test_signal_and_pnl_match_hand_calculation():
    df = sessions(3, momentum=0.0, seed=1)
    tr = im.daily_trades(df)
    assert len(tr) == 2  # first session has no previous close
    d = tr.index[0]
    day_bars = df[df.index.normalize() == d]
    prev_close = df[df.index.normalize() < d]["close"].iloc[-1]
    sig = day_bars.loc[day_bars.index.strftime("%H:%M") == "09:59", "close"].iloc[0]
    entry = day_bars.loc[day_bars.index.strftime("%H:%M") == "15:30", "open"].iloc[0]
    exit_ = day_bars.loc[day_bars.index.strftime("%H:%M") == "15:59", "close"].iloc[0]
    side = np.sign(sig / prev_close - 1)
    assert tr.iloc[0]["gross"] == pytest.approx(side * (exit_ / entry - 1))
    assert tr.iloc[0]["net"] == pytest.approx(tr.iloc[0]["gross"] - 0.03 / entry)


def test_planted_momentum_is_detected_and_null_is_not():
    strong = im.daily_trades(sessions(300, momentum=0.6, seed=2))
    null = im.daily_trades(sessions(300, momentum=0.0, seed=3))
    assert im.stats(strong)["hac_t"] > 5
    assert abs(im.stats(null, "gross")["hac_t"]) < 3


def test_half_day_and_following_day_are_skipped():
    df = sessions(5, momentum=0.0, seed=4, half_day=2)
    tr = im.daily_trades(df)
    days = sorted(df.index.normalize().unique())
    assert days[2] not in tr.index  # half day lacks 15:30/15:59 bars
    assert days[3] not in tr.index  # its "previous close" was an early close
    assert days[4] in tr.index


def test_hac_t_matches_plain_t_for_iid_data():
    x = pd.Series(np.random.default_rng(5).normal(0.1, 1, 5000))
    plain = x.mean() / x.std(ddof=0) * np.sqrt(len(x))
    assert im.hac_t(x) == pytest.approx(plain, rel=0.05)


def test_cli_reports_verdict(tmp_path):
    paths = []
    for i, tk in enumerate(("SPY", "QQQ", "IWM", "DIA")):
        p = tmp_path / f"{tk}.csv"
        sessions(400, momentum=0.6, seed=10 + i).rename_axis("timestamp").to_csv(p)
        paths.append(f"{tk}={p}")
    out = tmp_path / "m"
    assert im.main([*paths, "--out", str(out)]) == 0
    assert "EDGE FOUND" in (out / "report.md").read_text()
