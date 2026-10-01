"""Small vectorized backtest harness for playground strategies.

Not a rigorous research tool -- just enough discipline (one-bar signal lag)
to keep the numbers from being meaningless, per playground/README.md.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def run_backtest(prices: pd.Series, signal: pd.Series) -> dict:
    """Backtest `signal` (position per day) against `prices`.

    The signal is shifted by one bar before being applied to next-day
    returns: a position computed from data through day t-1 only affects
    the return realized from t-1 to t, never the return that produced it.
    """
    rets = prices.pct_change()
    position = signal.reindex(prices.index).shift(1)
    strategy_rets = (position * rets).fillna(0.0)

    equity = (1.0 + strategy_rets).cumprod()
    n_years = max((prices.index[-1] - prices.index[0]).days / 365.25, 1e-9)
    total_return = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1.0 / n_years) - 1.0)
    ann_vol = float(strategy_rets.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
    ann_mean = float(strategy_rets.mean() * TRADING_DAYS_PER_YEAR)
    sharpe = ann_mean / ann_vol if ann_vol > 0 else np.nan
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())

    active = strategy_rets[position.fillna(0) != 0]
    hit_rate = float((active > 0).mean()) if len(active) else np.nan
    n_trades = int((position.fillna(0).diff().fillna(0) != 0).sum())

    return {
        "total_return": total_return,
        "cagr": cagr,
        "annualized_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "hit_rate": hit_rate,
        "n_trades": n_trades,
        "n_days": int(len(prices)),
        "equity_curve": equity,
    }


def print_metrics(ticker: str, strategy: str, metrics: dict) -> None:
    print(f"\n=== {strategy} on {ticker} ({metrics['n_days']} trading days) ===")
    print(f"Total return:     {metrics['total_return']:+.1%}")
    print(f"CAGR:             {metrics['cagr']:+.1%}")
    print(f"Annualized vol:   {metrics['annualized_vol']:.1%}")
    print(f"Sharpe (rf=0):    {metrics['sharpe']:.2f}")
    print(f"Max drawdown:     {metrics['max_drawdown']:.1%}")
    print(f"Hit rate:         {metrics['hit_rate']:.1%}")
    print(f"Trades:           {metrics['n_trades']}")


def plot_equity_curve(ticker: str, strategy: str, equity: pd.Series, out_path: str) -> None:
    """Lazily imports matplotlib so the harness works without it installed."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(equity.index, equity.values)
    ax.set_title(f"{strategy} on {ticker} -- equity curve (starts at 1.0)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Growth of $1")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"\nSaved equity curve to {out_path}")
