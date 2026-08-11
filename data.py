"""
Market data module.

Fetches OHLCV candles from Binance via CCXT and enriches them with
EMA and ATR indicators using Pandas.
"""

from __future__ import annotations

import pandas as pd

import config


def fetch_ohlcv(
    symbol: str = config.TRADING_SYMBOL,
    timeframe: str = config.TIMEFRAME,
    limit: int = config.CANDLE_LIMIT,
) -> pd.DataFrame:
    """
    Fetch the most recent *limit* candles and return a clean DataFrame
    with calculated indicators (EMA fast/slow, ATR).

    Parameters
    ----------
    symbol : str
        Trading pair, e.g. ``'BTC/USDT'``.
    timeframe : str
        Candle interval understood by CCXT, e.g. ``'1h'``.
    limit : int
        Number of candles to request.

    Returns
    -------
    pd.DataFrame
        Columns: timestamp, open, high, low, close, volume, ema_fast,
        ema_slow, atr.
    """
    raw_candles = config.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    df = pd.DataFrame(
        raw_candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )

    # CCXT timestamps are in milliseconds — convert to readable datetimes.
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    df = _add_indicators(df)
    return df


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Append EMA and ATR columns to *df* (modified in place, also returned)."""
    df["ema_fast"] = df["close"].ewm(span=config.EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=config.EMA_SLOW, adjust=False).mean()

    # True Range components
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Simple rolling-mean ATR over the configured period.
    df["atr"] = tr.rolling(window=config.ATR_PERIOD).mean()

    return df


def get_completed_candles(df: pd.DataFrame, count: int = 2) -> pd.DataFrame:
    """
    Return the last *count* **fully closed** candles.

    CCXT includes the currently forming candle as the final row; we exclude
    it so signal logic only operates on completed bars.
    """
    if len(df) < count + 1:
        raise ValueError(
            f"Need at least {count + 1} candles to extract {count} completed bars."
        )
    return df.iloc[-(count + 1) : -1].reset_index(drop=True)
