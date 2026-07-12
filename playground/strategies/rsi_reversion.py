"""RSI mean-reversion: go long when RSI drops below the oversold threshold,
flatten once it recovers above the overbought threshold."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def generate_signal(prices: pd.Series, window: int = 14,
                    oversold: float = 30.0, overbought: float = 70.0) -> pd.Series:
    rsi = _rsi(prices, window)
    position = pd.Series(0, index=prices.index, dtype=int)
    in_position = False
    for i, value in enumerate(rsi):
        if pd.isna(value):
            continue
        if not in_position and value < oversold:
            in_position = True
        elif in_position and value > overbought:
            in_position = False
        position.iloc[i] = int(in_position)
    return position
