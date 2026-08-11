"""
Strategy module.

EMA crossover signal detection, ATR-based position sizing, and
stop-loss / take-profit level calculation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

import config

Signal = Optional[Literal["BUY", "SELL"]]


@dataclass
class TradePlan:
    """All parameters needed to place and manage a single trade."""

    side: Literal["BUY", "SELL"]
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    atr: float


def evaluate_signal(completed_candles: pd.DataFrame) -> Signal:
    """
    Evaluate the last two **completed** candles for an EMA crossover signal.

    Expects exactly two rows: index 0 = previous candle, index 1 = latest
    completed candle.

    Returns
    -------
    ``'BUY'``  — fast EMA crossed above slow EMA.
    ``'SELL'`` — fast EMA crossed below slow EMA.
    ``None``   — no crossover on this bar.
    """
    if len(completed_candles) != 2:
        raise ValueError("evaluate_signal expects exactly 2 completed candles.")

    prev = completed_candles.iloc[0]
    latest = completed_candles.iloc[1]

    # Skip if indicators are not yet valid (NaN from warm-up period).
    required = ["ema_fast", "ema_slow", "atr"]
    if latest[required].isna().any() or prev[required].isna().any():
        return None

    fast_was_below = prev["ema_fast"] < prev["ema_slow"]
    fast_now_above = latest["ema_fast"] > latest["ema_slow"]

    fast_was_above = prev["ema_fast"] > prev["ema_slow"]
    fast_now_below = latest["ema_fast"] < latest["ema_slow"]

    if fast_was_below and fast_now_above:
        return "BUY"
    if fast_was_above and fast_now_below:
        return "SELL"

    return None


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    atr: float,
    side: Literal["BUY", "SELL"] = "BUY",
) -> float:
    """
    Size the order so that hitting the ATR stop-loss risks exactly
    ``RISK_PER_TRADE_PCT`` of the total account balance.

    For a long:  risk per coin = entry − stop  = ATR_SL_MULT × ATR
    For a short: risk per coin = stop − entry  = ATR_SL_MULT × ATR

    quantity = (balance × risk_pct) / (ATR_SL_MULT × ATR)
    """
    if atr <= 0 or entry_price <= 0 or account_balance <= 0:
        return 0.0

    risk_amount = account_balance * config.RISK_PER_TRADE_PCT
    stop_distance = config.ATR_SL_MULT * atr

    quantity = risk_amount / stop_distance
    return round(quantity, 8)


def calculate_sl_tp(
    entry_price: float,
    atr: float,
    side: Literal["BUY", "SELL"],
) -> tuple[float, float]:
    """
    Compute stop-loss and take-profit prices from ATR multiples.

    Long  → SL below entry, TP above entry.
    Short → SL above entry, TP below entry.
    """
    sl_distance = config.ATR_SL_MULT * atr
    tp_distance = config.ATR_TP_MULT * atr

    if side == "BUY":
        stop_loss = entry_price - sl_distance
        take_profit = entry_price + tp_distance
    else:
        stop_loss = entry_price + sl_distance
        take_profit = entry_price - tp_distance

    return round(stop_loss, 2), round(take_profit, 2)


def build_trade_plan(
    signal: Literal["BUY", "SELL"],
    account_balance: float,
    latest_candle: pd.Series,
) -> TradePlan:
    """
    Combine signal, sizing, and SL/TP into a single ``TradePlan``.
    """
    entry_price = float(latest_candle["close"])
    atr = float(latest_candle["atr"])

    quantity = calculate_position_size(account_balance, entry_price, atr, signal)
    stop_loss, take_profit = calculate_sl_tp(entry_price, atr, signal)

    return TradePlan(
        side=signal,
        quantity=quantity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        atr=atr,
    )
