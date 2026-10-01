"""Classic moving-average crossover: long when the fast SMA is above the
slow SMA, flat otherwise."""
from __future__ import annotations

import pandas as pd


def generate_signal(prices: pd.Series, fast: int = 20, slow: int = 100) -> pd.Series:
    fast_ma = prices.rolling(fast).mean()
    slow_ma = prices.rolling(slow).mean()
    return (fast_ma > slow_ma).astype(int)
