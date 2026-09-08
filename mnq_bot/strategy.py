"""QQQ (Nasdaq-100 ETF) 15m Opening Range Breakout — short-term day desk."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CET = ZoneInfo("Europe/Berlin")

# Display / trade symbol (Yahoo feed is QQQ).
SYMBOL = "QQQ"


@dataclass(frozen=True)
class MnqRules:
    """Session ORB rules. Price knobs are in QQQ dollars (not MNQ index points)."""

    or_hour_cet: int = 15
    or_minute_cet: int = 30
    or_duration_minutes: int = 15
    entry_start_hour_cet: int = 15
    entry_start_minute_cet: int = 45
    entry_end_hour_cet: int = 18
    entry_end_minute_cet: int = 0
    eod_hour_cet: int = 21
    eod_minute_cet: int = 0
    # ~$0.05–$0.15 buffer on QQQ (~ETF dollars), optionally floored by ATR.
    breakout_points: float = 0.08
    breakout_atr_mult: float = 0.05
    volume_sma_period: int = 20
    volume_mult: float = 1.25
    reward_risk: float = 2.0
    risk_pct: float = 0.005
    max_risk_pct: float = 0.10
    max_trades_per_day: int = 1
    atr_period: int = 14
    or_min_atr_mult: float = 0.15
    or_max_atr_mult: float = 5.0
    # Typical 15m OR width on QQQ is cents to a few dollars.
    min_or_points: float = 0.20
    max_or_points: float = 8.0
    trend_sma_period: int = 0
    long_only: bool = False
    require_close_break: bool = True
    use_vwap: bool = False
    session_bias: bool = False
    # Cap stop distance in QQQ dollars so $100 books can still size a trade.
    max_stop_points: float = 2.5
    # Skip tiny notionals (broker realism for fractional shares).
    min_notional: float = 5.0


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


def _breakout_buffer(rules: MnqRules, atr: float) -> float:
    fixed = float(rules.breakout_points)
    if rules.breakout_atr_mult > 0 and np.isfinite(atr) and atr > 0:
        return max(fixed, float(rules.breakout_atr_mult) * atr)
    return fixed


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
    if rules.volume_mult > 0:
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
    buffer = _breakout_buffer(rules, atr)
    long_trigger = or_high + buffer
    short_trigger = or_low - buffer
    high_raw = _field(row, "high")
    low_raw = _field(row, "low")
    high = float(high_raw) if high_raw is not None and pd.notna(high_raw) else close
    low = float(low_raw) if low_raw is not None and pd.notna(low_raw) else close
    if rules.require_close_break:
        long_break = close > long_trigger
        short_break = close < short_trigger
    else:
        long_break = high > long_trigger
        short_break = low < short_trigger
    trend = _field(row, "trend_sma")
    if long_break:
        if rules.use_vwap and close < float(vwap):
            return None
        if rules.session_bias and prev_close is not None and pd.notna(prev_close) and close < float(prev_close):
            return None
        if rules.trend_sma_period and trend is not None and pd.notna(trend) and close < float(trend):
            return None
        risk = close - mid
        if risk <= 0:
            return None
        if rules.max_stop_points > 0:
            risk = min(risk, float(rules.max_stop_points))
        stop = close - risk
        return MnqSignal(
            "long",
            "orb_long",
            close,
            stop,
            close + rules.reward_risk * risk,
            or_high,
            or_low,
        )
    if short_break:
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
        if rules.max_stop_points > 0:
            risk = min(risk, float(rules.max_stop_points))
        stop = close + risk
        return MnqSignal(
            "short",
            "orb_short",
            close,
            stop,
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


def size_shares(
    cash: float,
    entry: float,
    stop: float,
    *,
    rules: MnqRules | None = None,
) -> float:
    """Fractional QQQ shares sized by dollar risk (retail ETF realism)."""
    rules = rules or MnqRules()
    risk_per_share = abs(float(entry) - float(stop))
    if cash <= 0 or risk_per_share <= 0 or entry <= 0:
        return 0.0
    qty = (cash * rules.risk_pct) / risk_per_share
    max_by_risk = (cash * rules.max_risk_pct) / risk_per_share
    qty = min(qty, max_by_risk, cash / entry)
    if qty * entry < float(rules.min_notional):
        return 0.0
    return float(qty)


def size_contracts(
    cash: float,
    risk_pts: float,
    *,
    rules: MnqRules | None = None,
    point_value: float = 1.0,
    risk_frac: float | None = None,
    max_risk_frac: float | None = None,
    min_cash_for_one: float | None = None,
    min_margin: float | None = None,
    entry: float | None = None,
) -> tuple[float, bool]:
    """Back-compat wrapper → fractional ``size_shares``.

    ``risk_pts`` is the stop distance in QQQ dollars. ``forced`` is always False
    (no whole-lot rounding).
    """
    from dataclasses import replace

    del point_value, min_cash_for_one, min_margin
    rules = rules or MnqRules()
    if risk_frac is not None:
        rules = replace(rules, risk_pct=float(risk_frac))
    if max_risk_frac is not None:
        rules = replace(rules, max_risk_pct=float(max_risk_frac))
    px = float(entry) if entry and entry > 0 else max(float(risk_pts) * 50.0, 100.0)
    stop = px - abs(float(risk_pts))
    qty = size_shares(cash, px, stop, rules=rules)
    return qty, False
