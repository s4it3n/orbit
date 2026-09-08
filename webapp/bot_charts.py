"""Chart payloads for Gold / MNQ desks (Yahoo OHLCV + strategy overlays)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from orbit import data as orbit_data


def _last_float(row: pd.Series, key: str) -> float | None:
    val = row.get(key)
    if val is None or pd.isna(val):
        return None
    return float(val)


def gold_chart_payload(*, limit: int = 320) -> dict[str, Any]:
    from gold_bot import settings as gold_settings
    from gold_bot import strategy as gold_strategy
    from gold_bot.data import fetch_gold_hourly

    rules = gold_settings.rules_from_settings()
    frame = gold_strategy.add_indicators(fetch_gold_hourly(), rules)
    completed = frame.iloc[:-1] if len(frame) > 1 else frame
    tail = completed.tail(max(50, limit)).copy()
    if rules.trend_sma_period and rules.trend_sma_period > 1:
        tail["trend_ema"] = tail.get("trend_sma")
        overlay = "Trend SMA"
    else:
        overlay = None
    last = tail.iloc[-1]
    return {
        "ok": True,
        "symbol": "XAU/USD",
        "timeframe": "1h",
        "source": "yahoo_gc_f",
        "overlay_label": overlay,
        "candles": orbit_data.candles_for_chart(tail),
        "market": {
            "close": _last_float(last, "close"),
            "atr": _last_float(last, "atr"),
            "donchian_high": _last_float(last, "donchian_high"),
            "donchian_low": _last_float(last, "donchian_low"),
            "squeeze": bool(last["squeeze"]) if pd.notna(last.get("squeeze")) else None,
            "bar_time": str(last["timestamp"]),
        },
    }


def mnq_chart_payload(*, limit: int = 320) -> dict[str, Any]:
    from mnq_bot import live as mnq_live
    from mnq_bot import settings as mnq_settings
    from mnq_bot import strategy as mnq_strategy
    from mnq_bot.data import fetch_mnq_15m

    rules = mnq_settings.rules_from_settings()
    frame = mnq_strategy.add_indicators(fetch_mnq_15m(), rules)
    completed = frame.iloc[:-1] if len(frame) > 1 else frame
    tail = completed.tail(max(50, limit)).copy()
    if rules.trend_sma_period and rules.trend_sma_period > 1:
        tail["trend_ema"] = tail.get("trend_sma")
        overlay = "Trend SMA"
    else:
        overlay = None
    last = tail.iloc[-1]
    account = mnq_live._load()
    return {
        "ok": True,
        "symbol": "QQQ",
        "timeframe": "15m",
        "source": "yahoo_qqq",
        "overlay_label": overlay,
        "candles": orbit_data.candles_for_chart(tail),
        "market": {
            "close": _last_float(last, "close"),
            "atr": _last_float(last, "atr"),
            "vwap": _last_float(last, "vwap"),
            "volume": _last_float(last, "volume"),
            "volume_sma": _last_float(last, "volume_sma"),
            "or_high": float(account["or_high"]) if account.get("or_high") is not None else None,
            "or_low": float(account["or_low"]) if account.get("or_low") is not None else None,
            "bar_time": str(last["timestamp"]),
        },
    }
