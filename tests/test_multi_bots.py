"""Smoke tests for Gold and MNQ strategy modules using fixture OHLCV."""

import numpy as np
import pandas as pd

from gold_bot import strategy as gold
from gold_bot.engine import run_backtest as run_gold
from mnq_bot import strategy as mnq
from mnq_bot.engine import run_backtest as run_mnq


def _gold_frame(bars: int = 180) -> pd.DataFrame:
    stamps = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    close = 2300.0 + np.linspace(0, 30, bars) + np.sin(np.linspace(0, 16, bars))
    close[120:140] = close[119]
    close[140] = close[139] + 18
    return pd.DataFrame({
        "timestamp": stamps,
        "open": np.roll(close, 1),
        "high": close + 1.5,
        "low": close - 1.5,
        "close": close,
        "volume": np.full(bars, 1000.0),
    })


def _mnq_frame() -> pd.DataFrame:
    stamps = pd.date_range("2024-06-03 06:00", periods=26 * 5, freq="15min", tz="UTC")
    px = 20_000.0
    rows = []
    for ts in stamps:
        cet = ts.tz_convert(mnq.CET)
        shock = 8.0 if cet.hour == 15 and cet.minute == 45 else 0.4
        close = px + shock
        rows.append({
            "timestamp": ts,
            "open": px,
            "high": max(px, close) + 2,
            "low": min(px, close) - 2,
            "close": close,
            "volume": 1800 if cet.hour == 15 and cet.minute >= 45 else 700,
        })
        px = close
    return pd.DataFrame(rows)


def test_gold_indicators_and_backtest():
    result = run_gold(_gold_frame())
    assert result.bars > 100
    assert result.final_equity > 0
    assert isinstance(result.trades, list)


def test_gold_breakout_signal():
    row = pd.Series({
        "close": 2400.0,
        "donchian_high": 2380.0,
        "donchian_low": 2350.0,
        "atr": 10.0,
        "atr_sma": 20.0,
        "squeeze": True,
        "squeeze_bars": 2,
        "atr_pct": 10 / 2400,
        "prev_close": 2380.0,
        "ny_hour": 10,
    })
    signal = gold.evaluate_entry(row)
    assert signal is not None and signal.side == "long"


def test_mnq_orb_and_backtest():
    result = run_mnq(_mnq_frame())
    assert result.bars > 100
    assert result.final_equity > 0
    row = pd.Series({
        "close": 2010.0,
        "volume": 2000,
        "volume_sma": 1000,
        "cet_hour": 16,
        "cet_minute": 0,
        "atr": 12.0,
    })
    signal = mnq.evaluate_entry(row, or_high=2000.0, or_low=1990.0, trades_today=0)
    assert signal is not None and signal.side == "long"


def test_no_synthetic_generators():
    import gold_bot.engine as gold_engine
    import mnq_bot.engine as mnq_engine
    assert not hasattr(gold_engine, "_synthetic_xau")
    assert not hasattr(mnq_engine, "_synthetic_mnq")
