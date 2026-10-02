"""Tests for the playground BOS/CHoCH retest backtest (playground/smc)."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "playground", "smc"))
import backtest_smc as bt


def random_walk_bars(sessions: int = 40, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2024-01-02", periods=sessions)
    frames, px = [], 450.0
    for d in days:
        idx = pd.date_range(pd.Timestamp(f"{d:%Y-%m-%d} 09:30", tz=bt.ET),
                            periods=390, freq="1min")
        steps = rng.normal(0, 0.06, len(idx))
        close = px + np.cumsum(steps)
        open_ = np.r_[px, close[:-1]]
        wick = np.abs(rng.normal(0, 0.03, (2, len(idx))))
        frames.append(pd.DataFrame({
            "open": open_, "close": close,
            "high": np.maximum(open_, close) + wick[0],
            "low": np.minimum(open_, close) - wick[1], "volume": 1000.0}, index=idx))
        px = close[-1] + rng.normal(0, 0.5)
    return pd.concat(frames)


@pytest.mark.parametrize("mirror,side", [(False, "long"), (True, "short")])
def test_hand_built_setup_gives_one_exact_1r_trade(mirror, side):
    p = bt.Params(swing_n=2, entry_start="09:30")
    tr = bt.backtest(bt.synthetic_setup_bars(mirror), p)
    assert len(tr) == 1
    t = tr.iloc[0]
    assert t["side"] == side and t["reason"] == "target"
    assert t["gross_r"] == pytest.approx(1.0)
    expected_entry = 100.65 if not mirror else 99.35
    expected_stop = 98.94 if not mirror else 101.06
    assert t["entry"] == pytest.approx(expected_entry)
    assert t["stop"] == pytest.approx(expected_stop)
    assert t["net_r"] < t["gross_r"]  # costs are charged


def test_risk_bounds_skip_setup():
    p = bt.Params(swing_n=2, entry_start="09:30", max_risk=1.0)
    assert bt.backtest(bt.synthetic_setup_bars(), p).empty


def test_entry_window_blocks_early_bos():
    # the hand-built BOS happens around 09:59; a 10:30 window start blocks it
    p = bt.Params(swing_n=2, entry_start="10:30")
    assert bt.backtest(bt.synthetic_setup_bars(), p).empty


@pytest.mark.parametrize("tf", [1, 5, 15])
def test_no_lookahead_truncation_reproduces_closed_trades(tf):
    bars = bt.resample(random_walk_bars(), tf)
    p = bt.params_for_tf(bt.Params(), tf)
    full = bt.backtest(bars, p)
    assert len(full) > 0
    cut = len(bars) * 2 // 3
    part = bt.backtest(bars.iloc[:cut], p)
    closed = full[full["exit_idx"] < cut - 1].reset_index(drop=True)
    cols = ["side", "entry_time", "exit_time", "entry", "exit", "reason", "shares"]
    pd.testing.assert_frame_equal(closed[cols], part.iloc[:len(closed)][cols])


def test_random_walk_has_no_edge():
    bars = random_walk_bars(sessions=60)
    tr = bt.backtest(bars, bt.Params())
    s = bt.summarize(tr, bt.Params())
    assert s["trades"] > 30
    assert abs(s["avg_gross_r"]) < 0.3
    assert s["avg_net_r"] < s["avg_gross_r"]


def test_one_position_at_a_time_and_session_flat():
    tr = bt.backtest(random_walk_bars(), bt.Params())
    entries = pd.to_datetime(tr["entry_time"])
    exits = pd.to_datetime(tr["exit_time"])
    assert (entries.iloc[1:].to_numpy() >= exits.iloc[:-1].to_numpy()).all()
    assert (entries.dt.date == exits.dt.date).all()
    assert (exits.dt.hour * 60 + exits.dt.minute <= 15 * 60 + 55).all()


def test_resample_aligns_to_open_and_preserves_ohlc():
    bars = random_walk_bars(sessions=2)
    r = bt.resample(bars, 15)
    assert r.index[0].strftime("%H:%M") == "09:30"
    assert (r.index.minute % 15 == 0).all()
    first = bars.iloc[:15]
    assert r.iloc[0]["open"] == first["open"].iloc[0]
    assert r.iloc[0]["high"] == first["high"].max()
    assert r.iloc[0]["low"] == first["low"].min()
    assert r.iloc[0]["close"] == first["close"].iloc[-1]


def test_load_csv_naive_and_aware_timestamps_and_rth_filter(tmp_path):
    bars = random_walk_bars(sessions=1)
    pre = pd.DataFrame({"open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
                       index=[pd.Timestamp("2024-01-02 08:00", tz=bt.ET)])
    df = pd.concat([pre, bars])
    aware = tmp_path / "aware.csv"
    df.tz_convert("UTC").rename_axis("Datetime").to_csv(aware)
    naive = tmp_path / "naive.csv"
    df.tz_localize(None).rename_axis("timestamp").to_csv(naive)
    for path in (aware, naive):
        loaded = bt.load_csv(str(path))
        assert len(loaded) == 390
        assert loaded.index[0] == pd.Timestamp("2024-01-02 09:30", tz=bt.ET)


def test_cli_compare_writes_table(tmp_path):
    csv = tmp_path / "rw.csv"
    random_walk_bars(sessions=20).rename_axis("timestamp").to_csv(csv)
    out = tmp_path / "out"
    assert bt.main([str(csv), "--compare", "1,5,15", "--out", str(out)]) == 0
    table = (out / "compare.txt").read_text()
    assert "1m" in table and "15m" in table


def test_load_csv_handles_dst_change_with_mixed_offsets(tmp_path):
    idx = [pd.Timestamp("2024-11-01 09:30", tz=bt.ET),
           pd.Timestamp("2024-11-04 09:30", tz=bt.ET)]  # EDT then EST
    df = pd.DataFrame({"open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
                       "close": [1.0, 2.0], "volume": [0, 0]}, index=idx)
    path = tmp_path / "dst.csv"
    df.rename_axis("Datetime").to_csv(path)  # writes -04:00 and -05:00 offsets
    loaded = bt.load_csv(str(path))
    assert list(loaded.index) == idx


class _FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class _FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def get(self, url, headers, params, timeout):
        self.calls.append(dict(params))
        return self.pages.pop(0)


def _alpaca_bar(ts, px):
    return {"t": ts, "o": px, "h": px + 0.1, "l": px - 0.1, "c": px, "v": 100, "n": 1,
            "vw": px}


def test_alpaca_download_pages_and_parses():
    import run_spy
    pages = [_FakeResp(200, {"bars": [_alpaca_bar("2024-03-01T14:30:00Z", 500.0)],
                             "next_page_token": "abc"}),
             _FakeResp(200, {"bars": [_alpaca_bar("2024-03-01T14:31:00Z", 501.0)],
                             "next_page_token": None})]
    sess = _FakeSession(pages)
    df = run_spy.download_alpaca_1m("SPY", 1, "k", "s", session=sess)
    assert list(df["close"]) == [500.0, 501.0]
    assert df.index[0] == pd.Timestamp("2024-03-01 09:30", tz=bt.ET)
    assert sess.calls[1]["page_token"] == "abc"
    assert sess.calls[0]["adjustment"] == "raw" and sess.calls[0]["feed"] == "sip"


def test_alpaca_download_fails_loudly_on_error_or_empty():
    import run_spy
    with pytest.raises(RuntimeError, match="HTTP 403"):
        run_spy.download_alpaca_1m("SPY", 1, "k", "s",
                                   session=_FakeSession([_FakeResp(403, {"message": "no"})]))
    with pytest.raises(RuntimeError, match="no 1-minute bars"):
        run_spy.download_alpaca_1m("SPY", 1, "k", "s",
                                   session=_FakeSession([_FakeResp(200, {"bars": None})]))


def test_runner_reports_holdout_split_on_long_history(tmp_path, capsys):
    import run_spy
    csv = tmp_path / "long.csv"
    bars = random_walk_bars(sessions=330, seed=11)
    bars.rename_axis("timestamp").to_csv(csv)
    out = tmp_path / "res"
    rc = run_spy.main(["--csv", str(csv), "--out", str(out), "--compare", "1,5",
                       "--holdout-months", "2", "--plot-trades", "0"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "In-sample" in printed and "Holdout" in printed
    assert (out / "holdout" / "compare.txt").exists()
    assert (out / "in_sample" / "compare.txt").exists()


def test_sides_filter_restricts_direction():
    bars = random_walk_bars(sessions=30)
    both = bt.backtest(bars, bt.Params())
    longs = bt.backtest(bars, bt.Params(sides="long"))
    assert set(both["side"]) == {"long", "short"}
    assert set(longs["side"]) == {"long"}


def test_session_vwap_is_causal_and_filter_runs():
    bars = random_walk_bars(sessions=3)
    v = bt.session_vwap(bars)
    v_cut = bt.session_vwap(bars.iloc[:500])
    np.testing.assert_allclose(v[:500], v_cut)
    first = bars.iloc[0]
    assert v[0] == pytest.approx((first["high"] + first["low"] + first["close"]) / 3)
    tr = bt.backtest(random_walk_bars(sessions=30), bt.Params(vwap_filter=True))
    assert len(tr) > 0


def test_vwap_filter_fails_loudly_without_volume():
    bars = random_walk_bars(sessions=2).assign(volume=0.0)
    with pytest.raises(ValueError, match="volume"):
        bt.backtest(bars, bt.Params(vwap_filter=True))


def test_research_protocol_runs_end_to_end(tmp_path):
    import research_smc as rs
    assert len(rs.GRID) == 72 and len({str(g) for g in rs.GRID}) == 72
    assert 2.3 < rs.expected_max_t(72) < 2.5
    csv = tmp_path / "rw.csv"
    random_walk_bars(sessions=150, seed=5).rename_axis("timestamp").to_csv(csv)
    out = tmp_path / "research"
    assert rs.main([str(csv), "--holdout-months", "2", "--out", str(out),
                    "--workers", "1", "--grid-limit", "4"]) == 0
    report = (out / "report.md").read_text()
    assert "EDGE" in report
    assert (out / "in_sample_grid.csv").exists()


def test_confirm_runs_and_locks_variant(tmp_path):
    import confirm_smc as cs
    assert cs.VARIANT == {"tf": 5, "swing_n": 3, "rr": 1.0, "entry_start": "09:35",
                          "vwap_filter": False}
    paths = []
    for i, tk in enumerate(("AAA", "BBB")):
        csv = tmp_path / f"{tk}.csv"
        random_walk_bars(sessions=60, seed=20 + i).rename_axis("timestamp").to_csv(csv)
        paths.append(f"{tk}={csv}")
    out = tmp_path / "confirm"
    assert cs.main([*paths, "--out", str(out)]) == 0
    assert "CONFIRMED" in (out / "report.md").read_text()


def test_alpaca_download_retries_on_rate_limit():
    import run_spy
    pages = [_FakeResp(429, {"message": "too many requests."}),
             _FakeResp(200, {"bars": [_alpaca_bar("2024-03-01T14:30:00Z", 500.0)],
                             "next_page_token": None})]
    df = run_spy.download_alpaca_1m("SPY", 1, "k", "s", session=_FakeSession(pages),
                                    backoff=0.0)
    assert list(df["close"]) == [500.0]
    with pytest.raises(RuntimeError, match="HTTP 429"):
        run_spy.download_alpaca_1m(
            "SPY", 1, "k", "s", backoff=0.0, retries=1,
            session=_FakeSession([_FakeResp(429, {}), _FakeResp(429, {})]))


def test_alpaca_adjustment_is_passed_through():
    import run_spy
    sess = _FakeSession([_FakeResp(200, {"bars": [_alpaca_bar("2024-03-01T14:30:00Z", 1.0)],
                                         "next_page_token": None})])
    run_spy.download_alpaca_1m("SPY", 1, "k", "s", session=sess, adjustment="all")
    assert sess.calls[0]["adjustment"] == "all"
