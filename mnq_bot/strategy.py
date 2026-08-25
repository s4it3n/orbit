"""Micro E-mini Nasdaq-100 (MNQ) 15m Opening Range Breakout."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CET = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class MnqRules:
    or_hour_cet: int = 15
    or_minute_cet: int = 30
    or_duration_minutes: int = 15
    entry_start_hour_cet: int = 15
    entry_start_minute_cet: int = 45
    entry_end_hour_cet: int = 18
    entry_end_minute_cet: int = 0
    eod_hour_cet: int = 21
    eod_minute_cet: int = 0
    breakout_points: float = 2.0
    volume_sma_period: int = 20
    volume_mult: float = 1.25
    reward_risk: float = 2.0
    max_trades_per_day: int = 1
    atr_period: int = 14
    or_min_atr_mult: float = 0.15
    or_max_atr_mult: float = 5.0
    min_or_points: float = 8.0
    max_or_points: float = 250.0
    trend_sma_period: int = 0
    long_only: bool = False
    require_close_break: bool = True
    use_vwap: bool = False
    session_bias: bool = False


@dataclass(frozen=True)
class MnqSignal:
    side: str
    reason: str
    entry: float
    stop: float
    take_profit: float
    or_high: float
    or_low: float


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def add_indicators(frame: pd.DataFrame, rules: MnqRules | None = None) -> pd.DataFrame:
    rules = rules or MnqRules()
    out = frame.copy()
    ts = pd.to_datetime(out["timestamp"], utc=True).dt.tz_convert(CET)
    out["cet_date"] = ts.dt.date.astype(str)
    out["cet_hour"] = ts.dt.hour
    out["cet_minute"] = ts.dt.minute
    out["volume_sma"] = (
        out["volume"].rolling(rules.volume_sma_period, min_periods=rules.volume_sma_period).mean()
    )
    out["atr"] = _atr(out["high"], out["low"], out["close"], rules.atr_period)
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    cum_pv = (typical * out["volume"]).groupby(out["cet_date"]).cumsum()
    cum_vol = out["volume"].groupby(out["cet_date"]).cumsum().replace(0.0, np.nan)
    out["vwap"] = cum_pv / cum_vol
    daily_close = out.groupby("cet_date")["close"].last()
    out["prev_session_close"] = out["cet_date"].map(daily_close.shift(1))
    if rules.trend_sma_period and rules.trend_sma_period > 1:
        out["trend_sma"] = out["close"].rolling(
            rules.trend_sma_period, min_periods=rules.trend_sma_period
        ).mean()
    else:
        out["trend_sma"] = np.nan
    return out


def _field(row: object, name: str, default=None):
    if isinstance(row, pd.Series):
        return row.get(name, default)
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _or_window_minutes(rules: MnqRules) -> tuple[int, int]:
    start = rules.or_hour_cet * 60 + rules.or_minute_cet
    end = start + rules.or_duration_minutes
    return start, end


def _is_or_candle(row: object, rules: MnqRules) -> bool:
    minutes = int(_field(row, "cet_hour")) * 60 + int(_field(row, "cet_minute"))
    start, end = _or_window_minutes(rules)
    return start <= minutes < end


def _in_entry_window(row: object, rules: MnqRules) -> bool:
    minutes = int(_field(row, "cet_hour")) * 60 + int(_field(row, "cet_minute"))
    start = rules.entry_start_hour_cet * 60 + rules.entry_start_minute_cet
    end = rules.entry_end_hour_cet * 60 + rules.entry_end_minute_cet
    return start <= minutes <= end


def _is_eod(row: object, rules: MnqRules) -> bool:
    minutes = int(_field(row, "cet_hour")) * 60 + int(_field(row, "cet_minute"))
    eod = rules.eod_hour_cet * 60 + rules.eod_minute_cet
    return minutes >= eod


def evaluate_entry(
    row: object,
    *,
    or_high: float | None,
    or_low: float | None,
    trades_today: int,
    rules: MnqRules | None = None,
) -> MnqSignal | None:
    rules = rules or MnqRules()
    if or_high is None or or_low is None:
        return None
    if trades_today >= rules.max_trades_per_day:
        return None
    if not _in_entry_window(row, rules):
        return None
    if _is_or_candle(row, rules):
        return None
    volume_sma = _field(row, "volume_sma")
    if volume_sma is None or pd.isna(volume_sma):
        return None
    if float(_field(row, "volume")) < float(volume_sma) * rules.volume_mult:
        return None
    or_width = float(or_high) - float(or_low)
    if or_width <= 0:
        return None
    if or_width < rules.min_or_points or or_width > rules.max_or_points:
        return None
    atr_raw = _field(row, "atr")
    atr = float(atr_raw) if atr_raw is not None and pd.notna(atr_raw) else float("nan")
    if np.isfinite(atr) and atr > 0:
        if or_width < rules.or_min_atr_mult * atr:
            return None
        if or_width > rules.or_max_atr_mult * atr:
            return None
    close = float(_field(row, "close"))
    if rules.use_vwap:
        vwap = _field(row, "vwap")
        if vwap is None or pd.isna(vwap):
            return None
    prev_close = _field(row, "prev_session_close")
    mid = (or_high + or_low) / 2.0
    long_trigger = or_high + rules.breakout_points
    short_trigger = or_low - rules.breakout_points
    trend = _field(row, "trend_sma")
    if close > long_trigger:
        if rules.use_vwap and close < float(vwap):
            return None
        if rules.session_bias and prev_close is not None and pd.notna(prev_close) and close < float(prev_close):
            return None
        if rules.trend_sma_period and trend is not None and pd.notna(trend) and close < float(trend):
            return None
        risk = close - mid
        if risk <= 0:
            return None
        return MnqSignal(
            "long",
            "orb_long",
            close,
            mid,
            close + rules.reward_risk * risk,
            or_high,
            or_low,
        )
    if close < short_trigger:
        if rules.long_only:
            return None
        if rules.use_vwap and close > float(vwap):
            return None
        if rules.session_bias and prev_close is not None and pd.notna(prev_close) and close > float(prev_close):
            return None
        if rules.trend_sma_period and trend is not None and pd.notna(trend) and close > float(trend):
            return None
        risk = mid - close
        if risk <= 0:
            return None
        return MnqSignal(
            "short",
            "orb_short",
            close,
            mid,
            close - rules.reward_risk * risk,
            or_high,
            or_low,
        )
    return None


def should_force_flat(row: pd.Series, rules: MnqRules | None = None) -> bool:
    rules = rules or MnqRules()
    return _is_eod(row, rules)


def is_opening_range_bar(row: pd.Series, rules: MnqRules | None = None) -> bool:
    rules = rules or MnqRules()
    return _is_or_candle(row, rules)
