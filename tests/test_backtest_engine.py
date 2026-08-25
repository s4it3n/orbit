"""Orbit backtest engine."""

from __future__ import annotations

import numpy as np
import pandas as pd

from orbit import data
from backtest.config import BacktestConfig
from backtest.engine import run_backtest


def _frame(closes, start="2024-01-01"):
    n = len(closes)
    close = pd.Series(closes, dtype=float)
    frame = pd.DataFrame({
        "timestamp": pd.date_range(start, periods=n, freq="D", tz="UTC"),
        "open": close.shift(1).fillna(close.iloc[0]),
        "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e8,
    })
    return data.add_indicators(
        frame, trend_ema_period=20, momentum_lookbacks=(5, 10),
        volatility_period=10, atr_period=5, volume_lookback=5,
    )


def _cfg(**kwargs):
    base = dict(
        initial_capital=10_000.0, fee_rate=0.0, slippage_bps=0.0,
        universe=("AAA/USDT", "BBB/USDT"), regime_symbol="BTC/USDT",
        trend_ema_period=20, momentum_lookbacks=(5, 10), volatility_period=10,
        volume_lookback=5, atr_period=5, rank_buffer=2, min_hold_days=1,
        cooldown_days=0, min_momentum=-1.0, target_volatility=0.5,
        max_allocation_pct=1.0, max_portfolio_exposure=1.0, max_positions=3,
        atr_sl_mult=2.0, trail_atr_mult=3.0, take_profit_atr_mult=20.0,
        take_profit_fraction=0.50, fast_ema_period=10, rsi_period=5,
        rsi_threshold=0.0, min_history_bars=30, min_dollar_volume=1.0,
        daily_max_drawdown_pct=0.5,
    )
    base.update(kwargs)
    return BacktestConfig(**base)


def test_cash_when_regime_off():
    btc = _frame([200 - i * 0.8 for i in range(100)])
    aaa = _frame([20 + i for i in range(100)])
    panel = data.align_panel({"BTC/USDT": btc, "AAA/USDT": aaa, "BBB/USDT": aaa.copy()})
    result = run_backtest(panel, _cfg())
    assert result.skipped_signals.get("regime risk-off", 0) > 0


def test_take_profit_scales_out_half():
    # Strong uptrend so BTC stays risk-on and AAA stays ranked.
    btc = _frame([100 + i * 0.4 for i in range(80)])
    aaa = _frame([20 + i * 0.8 for i in range(80)])
    bbb = _frame([10 + i * 0.05 for i in range(80)])
    panel = data.align_panel({"BTC/USDT": btc, "AAA/USDT": aaa, "BBB/USDT": bbb})
    result = run_backtest(panel, _cfg(
        universe=("AAA/USDT",),
        max_positions=1,
        take_profit_atr_mult=0.25,
        trail_atr_mult=50.0,
        atr_sl_mult=50.0,
        min_hold_days=20,
    ))
    assert any(trade["reason"] == "take_profit" for trade in result.trades)


def test_unlisted_stays_nan():
    btc = _frame([100 + i * 0.5 for i in range(80)])
    aaa = _frame([50 + i for i in range(80)])
    bbb = _frame([10.0] * 60 + [10 + i for i in range(20)])
    bbb.loc[:59, ["open", "high", "low", "close", "volume"]] = np.nan
    panel = data.align_panel({"BTC/USDT": btc, "AAA/USDT": aaa, "BBB/USDT": bbb})
    assert np.isnan(panel.row("close", 10)[panel.index_of("BBB/USDT")])
