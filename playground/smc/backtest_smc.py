#!/usr/bin/env python3
"""BOS/CHoCH retest backtest for intraday bars (SPY 1-minute and higher).

Playground code -- not part of the audited AMPE pipeline (see
playground/README.md and playground/smc/README.md for the full rule set).

Strategy (long side; shorts are the exact mirror on negated prices):
  1. Fractal swings with `swing_n` bars each side, confirmed `swing_n` bars
     later (no lookahead).
  2. Bearish context: last swing high < previous swing high AND last swing
     low < previous swing low.
  3. CHoCH: a bar closes above the last (lower) swing high. That price is the
     CHoCH level; the lowest low since that swing high is the origin low.
  4. BOS: a new swing high forms after the CHoCH and a bar closes above it.
  5. Entry: limit buy at the CHoCH level, live from the bar after the BOS.
  6. Stop: origin low - stop_buffer. Target: entry + rr * risk.

Examples:
  python playground/smc/backtest_smc.py spy_1min.csv
  python playground/smc/backtest_smc.py spy_1min.csv --timeframe 5
  python playground/smc/backtest_smc.py spy_1min.csv --compare 1,5,15,30,60
  python playground/smc/backtest_smc.py --selftest
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import asdict, dataclass, replace
from itertools import pairwise

import numpy as np
import pandas as pd

ET = "America/New_York"
RTH_OPEN_MIN = 9 * 60 + 30
RTH_CLOSE_MIN = 16 * 60


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Params:
    swing_n: int = 5
    rr: float = 1.0
    stop_buffer: float = 0.01
    min_risk: float = 0.10
    max_risk: float = 3.00
    max_armed_bars: int = 90
    entry_start: str = "09:35"
    entry_end: str = "15:30"
    flatten: str = "15:55"
    commission: float = 0.005  # $/share/side
    slippage: float = 0.01  # $/share on stop and flatten exits
    equity: float = 100_000.0
    risk_pct: float = 1.0  # % of equity risked per trade
    max_leverage: float = 4.0
    carry: bool = False  # keep swing structure across sessions


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def params_for_tf(base: Params, tf: int, scale: bool = True) -> Params:
    """Scale bar-count and $-risk settings for an N-minute timeframe."""
    if tf <= 1 or not scale:
        return base
    root = math.sqrt(tf)
    return replace(
        base,
        swing_n=max(2, round(base.swing_n / root)),
        min_risk=base.min_risk * root,
        max_risk=base.max_risk * root,
        max_armed_bars=max(3, round(base.max_armed_bars / tf)),
        carry=base.carry or tf >= 15,
    )


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load_csv(path: str, tz: str = ET) -> pd.DataFrame:
    """Load OHLC(V) bars, convert to ET, keep regular trading hours only.

    Naive timestamps are assumed to be in `tz`; tz-aware ones are converted.
    Bars are assumed stamped at their START.
    """
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    ts_col = next((c for c in ("timestamp", "datetime", "date", "time") if c in df.columns),
                  df.columns[0])
    raw = df[ts_col].astype(str)
    # Offsets like "-04:00"/"+00:00" or a trailing "Z" mean tz-aware stamps;
    # parse via UTC so files spanning a DST change (mixed offsets) work.
    if raw.str.contains(r"(?:[+-]\d{2}:?\d{2}|Z)$", regex=True).all():
        ts = pd.to_datetime(raw, utc=True)
    else:
        ts = pd.to_datetime(raw).dt.tz_localize(tz, ambiguous="infer",
                                                nonexistent="shift_forward")
    ts = ts.dt.tz_convert(ET)
    missing = [c for c in ("open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}; have {list(df.columns)}")
    out = pd.DataFrame(
        {c: pd.to_numeric(df[c], errors="coerce") for c in ("open", "high", "low", "close")},
    )
    out["volume"] = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df else 0.0
    out.index = pd.DatetimeIndex(ts, name="timestamp")
    return prepare_bars(out)


def prepare_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Sort, de-duplicate, drop NaNs and keep 09:30 <= t < 16:00 ET."""
    if df.index.tz is None:
        df = df.tz_localize(ET)
    else:
        df = df.tz_convert(ET)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])
    mins = df.index.hour * 60 + df.index.minute
    df = df[(mins >= RTH_OPEN_MIN) & (mins < RTH_CLOSE_MIN)]
    if "volume" not in df:
        df = df.assign(volume=0.0)
    return df


def resample(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    """Build tf-minute bars aligned to the 09:30 open, stamped at bar start."""
    if tf <= 1:
        return df
    mins = df.index.hour * 60 + df.index.minute - RTH_OPEN_MIN
    bucket_start = df.index.normalize() + pd.to_timedelta(
        RTH_OPEN_MIN + (mins // tf) * tf, unit="min")
    g = df.groupby(bucket_start)
    out = pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum(),
    })
    out.index.name = "timestamp"
    return out


# --------------------------------------------------------------------------
# Structure detector (long side; short side runs on negated prices)
# --------------------------------------------------------------------------
@dataclass
class Setup:
    choch_level: float  # transformed price space
    origin_low: float
    sh_idx: int
    choch_idx: int
    bos_level: float = math.nan
    bos_idx: int = -1
    armed_from: int = -1  # first bar the limit order is live


class Detector:
    def __init__(self, h: np.ndarray, lo: np.ndarray, c: np.ndarray, n: int):
        self.h, self.lo, self.c, self.n = h, lo, c, n
        self.reset(0)

    def reset(self, start: int) -> None:
        self.start = start  # first bar of the current structure segment
        self.sh: list[tuple[int, float]] = []
        self.sl: list[tuple[int, float]] = []
        self.used_sh: set[int] = set()
        self.setup: Setup | None = None

    def _confirm_swings(self, t: int) -> None:
        n, k = self.n, t - self.n
        if k - n < self.start:
            return
        h, lo = self.h, self.lo
        if h[k] > h[k - n:k].max() and h[k] >= h[k + 1:t + 1].max():
            self.sh.append((k, float(h[k])))
        if lo[k] < lo[k - n:k].min() and lo[k] <= lo[k + 1:t + 1].min():
            self.sl.append((k, float(lo[k])))

    def update(self, t: int) -> Setup | None:
        """Process bar t's close. Returns a setup if its BOS fired on bar t."""
        self._confirm_swings(t)
        s = self.setup
        if s is not None:
            if s.armed_from >= 0:
                return None  # armed setups are managed by the engine
            if self.lo[t] < s.origin_low:
                self.setup = None
                return None
            later = [p for (i, p) in self.sh if i >= s.choch_idx]
            if later and self.c[t] > later[-1]:
                s.bos_level, s.bos_idx, s.armed_from = later[-1], t, t + 1
                return s
            return None
        if len(self.sh) < 2 or len(self.sl) < 2:
            return None
        (_, sh_prev), (sh_idx, sh_last) = self.sh[-2], self.sh[-1]
        sl_prev, sl_last = self.sl[-2][1], self.sl[-1][1]
        if sh_idx in self.used_sh or not (sh_last < sh_prev and sl_last < sl_prev):
            return None
        if self.c[t] > sh_last:
            self.used_sh.add(sh_idx)
            origin = float(self.lo[sh_idx:t + 1].min())
            self.setup = Setup(choch_level=sh_last, origin_low=origin,
                               sh_idx=sh_idx, choch_idx=t)
        return None


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
@dataclass
class Order:
    side: int  # +1 long, -1 short
    entry: float
    stop: float
    target: float
    armed_from: int
    expires: int  # last bar index (inclusive) the order may fill
    setup: Setup


def backtest(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Run the strategy over prepared bars; returns one row per trade."""
    if df.empty:
        return _empty_trades()
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    idx = df.index
    mins = (idx.hour * 60 + idx.minute).to_numpy()
    day = idx.normalize()
    new_session = np.r_[True, day[1:] != day[:-1]]
    e_start, e_end, flat_t = _hhmm(p.entry_start), _hhmm(p.entry_end), _hhmm(p.flatten)

    dets = {+1: Detector(h, lo, c, p.swing_n), -1: Detector(-lo, -h, -c, p.swing_n)}
    orders: dict[int, Order] = {}
    pos: dict | None = None
    equity = p.equity
    trades: list[dict] = []

    def close_pos(t: int, price: float, reason: str) -> None:
        nonlocal pos, equity
        side, shares = pos["side"], pos["shares"]
        gross = side * (price - pos["entry"]) * shares
        net = gross - 2 * p.commission * shares
        risk_d = pos["risk"] * shares
        equity += net
        s: Setup = pos["setup"]
        trades.append({
            "side": "long" if side > 0 else "short",
            "entry_time": idx[pos["t"]], "exit_time": idx[t],
            "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
            "exit": price, "reason": reason, "shares": shares,
            "risk_per_share": pos["risk"],
            "gross_r": side * (price - pos["entry"]) / pos["risk"],
            "net_r": net / risk_d, "net_pnl": net, "equity": equity,
            "choch_time": idx[s.choch_idx], "bos_time": idx[s.bos_idx],
            "swing_time": idx[s.sh_idx],
            "choch_level": side * s.choch_level, "bos_level": side * s.bos_level,
            "origin": side * s.origin_low,
            "entry_idx": pos["t"], "exit_idx": t,
        })
        pos = None

    for t in range(len(df)):
        if new_session[t]:
            if pos is not None:  # data gap before flatten time: exit at last close
                close_pos(t - 1, c[t - 1] - pos["side"] * p.slippage, "session_end")
            orders.clear()
            for d in dets.values():
                if p.carry:
                    if d.setup is not None and d.setup.armed_from >= 0:
                        d.setup = None
                else:
                    d.reset(t)

        # 1) exits for an open position (from the bar after entry)
        if pos is not None and t > pos["t"]:
            side, stop, tgt = pos["side"], pos["stop"], pos["target"]
            if mins[t] >= flat_t:
                close_pos(t, o[t] - side * p.slippage, "flatten")
            elif side * (o[t] - stop) <= 0:
                close_pos(t, o[t] - side * p.slippage, "stop_gap")
            elif side * (o[t] - tgt) >= 0:
                close_pos(t, o[t], "target_gap")
            elif (lo[t] <= stop) if side > 0 else (h[t] >= stop):
                close_pos(t, stop - side * p.slippage, "stop")
            elif (h[t] >= tgt) if side > 0 else (lo[t] <= tgt):
                close_pos(t, tgt, "target")

        # 2) fills of live limit orders (armed on an earlier bar's close)
        if pos is None and orders and mins[t] < e_end:
            touched = [od for od in orders.values()
                       if od.armed_from <= t <= od.expires
                       and ((lo[t] <= od.entry) if od.side > 0 else (h[t] >= od.entry))]
            if touched:
                od = min(touched, key=lambda x: abs(o[t] - x.entry))
                fill = min(o[t], od.entry) if od.side > 0 else max(o[t], od.entry)
                risk = abs(od.entry - od.stop)
                shares = math.floor(min(equity * p.risk_pct / 100 / risk,
                                        equity * p.max_leverage / fill))
                orders.clear()
                for d in dets.values():
                    d.setup = None
                if shares > 0:
                    pos = {"side": od.side, "entry": fill, "stop": od.stop,
                           "target": od.target, "risk": risk, "shares": shares,
                           "t": t, "setup": od.setup}
                    # same-bar stop check (conservative: target never on fill bar)
                    if od.side * (o[t] - od.stop) <= 0:
                        close_pos(t, o[t] - od.side * p.slippage, "stop_gap")
                    elif (lo[t] <= od.stop) if od.side > 0 else (h[t] >= od.stop):
                        close_pos(t, od.stop - od.side * p.slippage, "stop")

        # 3) structure update on bar t's close; arm new orders for t+1
        for side, d in dets.items():
            s = d.update(t)
            if s is None:
                continue
            ok = pos is None and e_start <= mins[t] < e_end
            entry = side * s.choch_level
            stop = side * (s.origin_low - p.stop_buffer)
            risk = abs(entry - stop)
            if ok and p.min_risk <= risk <= p.max_risk:
                orders[side] = Order(side, entry, stop, entry + side * p.rr * risk,
                                     t + 1, t + p.max_armed_bars, s)
            else:
                d.setup = None

        # 4) expire / invalidate orders; discard setups while in a position
        for side in list(orders):
            od = orders[side]
            broken = (lo[t] <= od.stop + p.stop_buffer if side > 0
                      else h[t] >= od.stop - p.stop_buffer)
            if t >= od.expires or mins[t] >= e_end or (t >= od.armed_from and broken):
                del orders[side]
                dets[side].setup = None
        if pos is not None:
            orders.clear()
            for d in dets.values():
                d.setup = None

    if pos is not None:
        t = len(df) - 1
        close_pos(t, c[t] - pos["side"] * p.slippage, "end_of_data")
    return pd.DataFrame(trades) if trades else _empty_trades()


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=["side", "entry_time", "exit_time", "entry", "stop",
                                 "target", "exit", "reason", "shares", "gross_r",
                                 "net_r", "net_pnl", "equity"])


# --------------------------------------------------------------------------
# Stats and reports
# --------------------------------------------------------------------------
def summarize(trades: pd.DataFrame, p: Params) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    net_r = trades["net_r"].astype(float)
    eq = np.r_[p.equity, trades["equity"].astype(float).to_numpy()]
    dd = eq / np.maximum.accumulate(eq) - 1
    wins = trades.loc[trades["net_pnl"] > 0, "net_pnl"].sum()
    losses = -trades.loc[trades["net_pnl"] < 0, "net_pnl"].sum()
    sd = net_r.std(ddof=1) if n > 1 else math.nan
    return {
        "trades": n,
        "longs": int((trades["side"] == "long").sum()),
        "shorts": int((trades["side"] == "short").sum()),
        "win_rate": float((trades["gross_r"] > 0).mean()),
        "avg_gross_r": float(trades["gross_r"].mean()),
        "avg_net_r": float(net_r.mean()),
        "total_net_r": float(net_r.sum()),
        "t_stat": float(net_r.mean() / sd * math.sqrt(n)) if sd and sd > 0 else math.nan,
        "profit_factor": float(wins / losses) if losses > 0 else math.inf,
        "return_pct": float((eq[-1] / p.equity - 1) * 100),
        "max_dd_pct": float(dd.min() * 100),
        "avg_risk_usd": float(trades["risk_per_share"].mean()),
    }


def format_summary(rows: list[dict]) -> str:
    cols = [("tf", "{}"), ("bars", "{}"), ("trades", "{}"), ("longs", "{}"),
            ("shorts", "{}"), ("win_rate", "{:.1%}"), ("avg_gross_r", "{:+.3f}"),
            ("avg_net_r", "{:+.3f}"), ("total_net_r", "{:+.1f}"), ("t_stat", "{:+.2f}"),
            ("profit_factor", "{:.2f}"), ("return_pct", "{:+.2f}%"),
            ("max_dd_pct", "{:.2f}%"), ("avg_risk_usd", "${:.2f}")]
    table = [[k for k, _ in cols]]
    for r in rows:
        table.append([fmt.format(r[k]) if k in r and r[k] is not None else "-"
                      for k, fmt in cols])
    widths = [max(len(row[i]) for row in table) for i in range(len(cols))]
    return "\n".join("  ".join(v.rjust(w) for v, w in zip(row, widths, strict=True))
                     for row in table)


def write_report(trades: pd.DataFrame, p: Params, out_dir: str, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
    if len(trades):
        ax1.plot(pd.to_datetime(trades["exit_time"]), trades["equity"], lw=1.2)
        ax2.hist(trades["net_r"].astype(float), bins=40)
    ax1.axhline(p.equity, color="grey", lw=0.8, ls="--")
    ax1.set_title(f"{title}: equity (net of costs)")
    ax2.set_title("Net R per trade")
    ax2.axvline(0, color="grey", lw=0.8)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "report.png"), dpi=110)
    plt.close(fig)


def plot_trades(df: pd.DataFrame, trades: pd.DataFrame, out_dir: str, n: int,
                pad: int = 30) -> list[str]:
    """Candle charts with swing, CHoCH, BOS, entry, stop and target for
    the first `n` trades, for visual spot-checks of the structure logic."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = []
    pos_of = {ts: i for i, ts in enumerate(df.index)}
    for k, tr in trades.head(n).iterrows():
        i0 = max(0, pos_of[tr["swing_time"]] - pad)
        i1 = min(len(df), tr["exit_idx"] + pad)
        w = df.iloc[i0:i1]
        x = np.arange(len(w))
        fig, ax = plt.subplots(figsize=(12, 6))
        up = w["close"] >= w["open"]
        ax.vlines(x, w["low"], w["high"], color="black", lw=0.6)
        ax.bar(x, (w["close"] - w["open"]).abs().clip(lower=1e-4),
               bottom=np.minimum(w["open"], w["close"]), width=0.7,
               color=np.where(up, "#2a9d8f", "#e76f51"))
        rel = {name: pos_of[tr[col]] - i0 for name, col in
               [("swing", "swing_time"), ("CHoCH", "choch_time"), ("BOS", "bos_time")]}
        rel["entry"], rel["exit"] = tr["entry_idx"] - i0, tr["exit_idx"] - i0
        for name, xi in rel.items():
            ax.axvline(xi, color="grey", ls=":", lw=0.8)
            ax.text(xi, ax.get_ylim()[1], name, rotation=90, va="top", fontsize=8)
        for lvl, col, lab in [(tr["entry"], "blue", "entry/CHoCH"),
                              (tr["stop"], "red", "stop"),
                              (tr["target"], "green", "target"),
                              (tr["bos_level"], "purple", "BOS level")]:
            ax.axhline(lvl, color=col, lw=0.9, ls="--", label=f"{lab} {lvl:.2f}")
        ax.set_xticks(x[::max(1, len(x) // 10)])
        ax.set_xticklabels([w.index[i].strftime("%m-%d %H:%M")
                            for i in x[::max(1, len(x) // 10)]], fontsize=7)
        ax.set_title(f"trade {k}: {tr['side']} {tr['reason']} net {tr['net_r']:+.2f}R")
        ax.legend(fontsize=8, loc="best")
        fig.tight_layout()
        path = os.path.join(out_dir, f"trade_{k:03d}.png")
        fig.savefig(path, dpi=100)
        plt.close(fig)
        paths.append(path)
    return paths


def run_timeframe(df1: pd.DataFrame, tf: int, base: Params, scale: bool = True
                  ) -> tuple[pd.DataFrame, pd.DataFrame, Params]:
    bars = resample(df1, tf)
    p = params_for_tf(base, tf, scale)
    return bars, backtest(bars, p), p


# --------------------------------------------------------------------------
# Self-test: a hand-built long setup and its mirrored short
# --------------------------------------------------------------------------
SELFTEST_WAYPOINTS = [100.0, 101.0, 99.5, 100.6, 99.0, 101.2, 100.8, 101.6, 100.6, 103.5]


def synthetic_setup_bars(mirror: bool = False, leg: int = 4,
                         day: str = "2024-01-02") -> pd.DataFrame:
    """Piecewise-linear path: lower highs/lows, CHoCH, BOS, retest, rally."""
    pts = np.array(SELFTEST_WAYPOINTS)
    if mirror:
        pts = 200.0 - pts
    closes = [pts[0]]
    for a, b in pairwise(pts):
        closes.extend(np.linspace(a, b, leg + 1)[1:])
    closes = np.array(closes)
    opens = np.r_[closes[0], closes[:-1]]
    highs = np.maximum(opens, closes) + 0.05
    lows = np.minimum(opens, closes) - 0.05
    start = pd.Timestamp(f"{day} 09:30", tz=ET)
    idx = pd.date_range(start, periods=len(closes), freq="1min")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": 0.0}, index=idx)


def selftest() -> int:
    p = Params(swing_n=2, entry_start="09:30")
    ok = True
    for mirror in (False, True):
        tr = backtest(synthetic_setup_bars(mirror), p)
        side = "short" if mirror else "long"
        good = len(tr) == 1 and tr.iloc[0]["side"] == side and \
            abs(tr.iloc[0]["gross_r"] - 1.0) < 1e-9
        ok &= good
        print(f"{side}: {'OK' if good else 'FAIL'}")
        if len(tr):
            print(tr[["side", "entry", "stop", "target", "exit", "reason", "gross_r",
                      "net_r"]].to_string(index=False))
    return 0 if ok else 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_params(a: argparse.Namespace) -> Params:
    return Params(swing_n=a.swing_n, rr=a.rr, stop_buffer=a.stop_buffer,
                  min_risk=a.min_risk, max_risk=a.max_risk,
                  max_armed_bars=a.max_armed_bars, entry_start=a.entry_start,
                  entry_end=a.entry_end, flatten=a.flatten, commission=a.commission,
                  slippage=a.slippage, equity=a.equity, risk_pct=a.risk_pct,
                  max_leverage=a.max_leverage, carry=a.carry)


def parse_args(argv=None) -> argparse.Namespace:
    d = Params()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="1-minute OHLC CSV")
    ap.add_argument("--timeframe", type=int, default=1)
    ap.add_argument("--compare", help="comma-separated timeframes, e.g. 1,5,15,30,60")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--plot-trades", type=int, default=0,
                    help="write candle charts for the first N trades")
    for name, typ in [("swing_n", int), ("rr", float), ("stop_buffer", float),
                      ("min_risk", float), ("max_risk", float), ("max_armed_bars", int),
                      ("entry_start", str), ("entry_end", str), ("flatten", str),
                      ("commission", float), ("slippage", float), ("equity", float),
                      ("risk_pct", float), ("max_leverage", float)]:
        ap.add_argument("--" + name.replace("_", "-"), dest=name, type=typ,
                        default=getattr(d, name))
    ap.add_argument("--carry", action="store_true", help="keep structure across sessions")
    ap.add_argument("--no-scale", action="store_true",
                    help="do not rescale settings for higher timeframes")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--tz", default=ET, help="timezone of naive timestamps")
    ap.add_argument("--out", default="backtest_out")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.csv:
        print("error: a CSV path is required (or --selftest)", file=sys.stderr)
        return 2
    df = load_csv(a.csv, tz=a.tz)
    if a.start:
        df = df[df.index >= pd.Timestamp(a.start, tz=ET)]
    if a.end:
        df = df[df.index < pd.Timestamp(a.end, tz=ET) + pd.Timedelta(days=1)]
    if df.empty:
        print("error: no regular-hours bars in the selected range", file=sys.stderr)
        return 1
    base = build_params(a)
    days = df.index.normalize().nunique()
    print(f"data: {len(df)} 1-min RTH bars, {days} sessions, "
          f"{df.index[0]:%Y-%m-%d} .. {df.index[-1]:%Y-%m-%d}")
    os.makedirs(a.out, exist_ok=True)

    if a.compare:
        rows = []
        for tf in [int(x) for x in a.compare.split(",")]:
            bars, tr, p = run_timeframe(df, tf, base, scale=not a.no_scale)
            tr.to_csv(os.path.join(a.out, f"trades_{tf}m.csv"), index=False)
            rows.append({"tf": f"{tf}m", "bars": len(bars), **summarize(tr, p)})
        table = format_summary(rows)
        print(table)
        pd.DataFrame(rows).to_csv(os.path.join(a.out, "compare.csv"), index=False)
        with open(os.path.join(a.out, "compare.txt"), "w") as f:
            f.write(table + "\n")
        return 0

    bars, tr, p = run_timeframe(df, a.timeframe, base, scale=not a.no_scale)
    tr.to_csv(os.path.join(a.out, "trades.csv"), index=False)
    print(f"params: {asdict(p)}")
    print(format_summary([{"tf": f"{a.timeframe}m", "bars": len(bars), **summarize(tr, p)}]))
    write_report(tr, p, a.out, f"{a.timeframe}m BOS/CHoCH retest")
    if a.plot_trades and len(tr):
        plot_trades(bars, tr, a.out, a.plot_trades)
    print(f"wrote {a.out}/trades.csv and {a.out}/report.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
