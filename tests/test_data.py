"""Orbit data indicators."""

import pandas as pd

from orbit import data


def test_indicators_and_panel():
    closes = [100 + i for i in range(250)]
    frame = pd.DataFrame({
        "timestamp": pd.date_range("2023-01-01", periods=len(closes), freq="D", tz="UTC"),
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes, "volume": 1e6,
    })
    out = data.add_indicators(
        frame, trend_ema_period=50, momentum_lookbacks=(10, 20),
        volatility_period=20, atr_period=14, volume_lookback=20,
    )
    assert "trend_ema" in out.columns and "score" in out.columns
    assert "fast_ema" in out.columns and "rsi" in out.columns
    assert "breadth_ema" in out.columns
    assert "roc_14" in out.columns
    assert "breakout_level" not in out.columns
    assert pd.isna(out["trend_ema"].iloc[20])
