"""XAU/USD 1H Donchian channel-expansion volatility breakout."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GoldRules:
    donchian_period: int = 22
    atr_period: int = 14
    atr_sma_period: int = 50
    breakout_atr_mult: float = 0.1
    risk_pct: float = 0.009
    initial_stop_atr: float = 2.5
    breakeven_atr: float = 1.5
    trail_atr: float = 2.5
    time_stop_hours: int = 48
    # Quality filters (core Donchian + squeeze entry is unchanged).
    squeeze_min_bars: int = 1
    trend_sma_period: int = 0  # 0 disables the SMA trend filter
    long_only: bool = False
    session_start_hour: int | None = None  # America/New_York hour, inclusive
    session_end_hour: int | None = None  # exclusive
    min_atr_pct: float = 0.0
    max_atr_pct: float = 0.05
    require_inside_prev: bool = True


@dataclass(frozen=True)
class GoldSignal:
    side: str  # "long" | "short"
    reason: str
    entry: float
    stop: float
    atr: float


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def add_indicators(frame: pd.DataFrame, rules: GoldRules | None = None) -> pd.DataFrame:
    rules = rules or GoldRules()
    out = frame.copy()
    ts = pd.to_datetime(out["timestamp"], utc=True)
    ny = ts.dt.tz_convert("America/New_York")
    out["ny_hour"] = ny.dt.hour
    out["donchian_high"] = out["high"].rolling(rules.donchian_period).max().shift(1)
    out["donchian_low"] = out["low"].rolling(rules.donchian_period).min().shift(1)
    out["atr"] = _atr(out["high"], out["low"], out["close"], rules.atr_period)
    out["atr_sma"] = out["atr"].rolling(rules.atr_sma_period, min_periods=rules.atr_sma_period).mean()
    out["atr_pct"] = out["atr"] / out["close"].replace(0.0, np.nan)
    out["squeeze"] = out["atr"] < out["atr_sma"]
    out["squeeze_bars"] = (
        out["squeeze"].groupby((~out["squeeze"]).cumsum()).cumsum().astype(float)
    )
    if rules.trend_sma_period and rules.trend_sma_period > 1:
        out["trend_sma"] = (
            out["close"].rolling(rules.trend_sma_period, min_periods=rules.trend_sma_period).mean()
        )
    else:
        out["trend_sma"] = np.nan
    out["prev_close"] = out["close"].shift(1)
    return out


def _field(row: object, name: str, default=None):
    if isinstance(row, pd.Series):
        return row.get(name, default)
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _in_session(row: object, rules: GoldRules) -> bool:
    if rules.session_start_hour is None or rules.session_end_hour is None:
        return True
    hour = int(_field(row, "ny_hour"))
    start = rules.session_start_hour
    end = rules.session_end_hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def evaluate_entry(row: object, rules: GoldRules | None = None) -> GoldSignal | None:
    """Return a breakout signal on a completed 1H bar, or None."""
    rules = rules or GoldRules()
    needed = ("close", "donchian_high", "donchian_low", "atr", "atr_sma", "squeeze")
    values = {name: _field(row, name) for name in needed}
    if any(val is None or pd.isna(val) for val in values.values()):
        return None
    if not _in_session(row, rules):
        return None
    if not bool(values["squeeze"]):
        return None
    squeeze_raw = _field(row, "squeeze_bars", 1.0)
    squeeze_bars = float(squeeze_raw) if squeeze_raw is not None and pd.notna(squeeze_raw) else 1.0
    if squeeze_bars < rules.squeeze_min_bars:
        return None
    atr = float(values["atr"])
    close = float(values["close"])
    if close <= 0 or atr <= 0:
        return None
    atr_pct_raw = _field(row, "atr_pct")
    atr_pct = float(atr_pct_raw) if atr_pct_raw is not None and pd.notna(atr_pct_raw) else atr / close
    if atr_pct < rules.min_atr_pct or atr_pct > rules.max_atr_pct:
        return None
    high_band = float(values["donchian_high"]) + rules.breakout_atr_mult * atr
    low_band = float(values["donchian_low"]) - rules.breakout_atr_mult * atr
    prev_close = _field(row, "prev_close")
    if rules.require_inside_prev and prev_close is not None and pd.notna(prev_close):
        prev = float(prev_close)
        broke_up = close > high_band and prev <= high_band
        broke_down = close < low_band and prev >= low_band
    else:
        broke_up = close > high_band
        broke_down = close < low_band
    trend = _field(row, "trend_sma")
    if broke_up:
        if rules.trend_sma_period and trend is not None and pd.notna(trend) and close < float(trend):
            return None
        stop = close - rules.initial_stop_atr * atr
        return GoldSignal("long", "donchian_breakout_long", close, stop, atr)
    if broke_down:
        if rules.long_only:
            return None
        if rules.trend_sma_period and trend is not None and pd.notna(trend) and close > float(trend):
            return None
        stop = close + rules.initial_stop_atr * atr
        return GoldSignal("short", "donchian_breakout_short", close, stop, atr)
    return None


def position_size(equity: float, entry: float, stop: float, rules: GoldRules | None = None) -> float:
    rules = rules or GoldRules()
    risk_per_unit = abs(entry - stop)
    if equity <= 0 or risk_per_unit <= 0 or entry <= 0:
        return 0.0
    qty = (equity * rules.risk_pct) / risk_per_unit
    return min(qty, equity / entry)


def update_stop(
    side: str,
    entry: float,
    current_stop: float,
    extreme: float,
    atr: float,
    *,
    rules: GoldRules | None = None,
) -> float:
    """Breakeven at ``breakeven_atr``, then ATR trail from peak/trough.

    After the trade extends +1.5 ATR beyond the breakeven trigger, the trail
    tightens by 0.25 ATR (floored at 2.0) to limit give-back without choking
    trend follow-through.
    """
    rules = rules or GoldRules()
    if atr <= 0:
        return current_stop
    profit_atr = abs(extreme - entry) / atr
    trail_mult = rules.trail_atr
    if profit_atr >= rules.breakeven_atr + 1.5:
        trail_mult = max(2.0, rules.trail_atr - 0.25)
    if side == "long":
        if extreme >= entry + rules.breakeven_atr * atr:
            current_stop = max(current_stop, entry)
        trail = extreme - trail_mult * atr
        return max(current_stop, trail)
    if extreme <= entry - rules.breakeven_atr * atr:
        current_stop = min(current_stop, entry)
    trail = extreme + trail_mult * atr
    return min(current_stop, trail)


def hours_held(entry_ts: pd.Timestamp, now_ts: pd.Timestamp) -> float:
    return (now_ts - entry_ts).total_seconds() / 3600.0
