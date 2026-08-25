"""Thread-safe JSON state and settings for Orbit."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import universe

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "bot_state.json"
SETTINGS_FILE = ROOT / "settings.json"

MAX_OPERATIONS = 100
MAX_LOG_LINES = 200
_lock = threading.RLock()

DEFAULT_SETTINGS: dict[str, Any] = {
    # Off until you click Start. Paper trading hits Binance spot testnet.
    "bot_enabled": False,
    "universe": list(universe.DEFAULT_UNIVERSE),
    "timeframe": "1d",
    "trend_ema_period": 200,
    "fast_ema_period": 50,
    "breadth_ema_period": 20,
    "rsi_period": 14,
    "rsi_threshold": 45.0,
    "full_capacity_rsi": 50.0,
    "defensive_size_mult": 0.50,
    "momentum_lookbacks": [7, 14, 30],
    "volatility_period": 30,
    "volume_lookback": 30,
    "atr_period": 14,
    "rank_buffer": 3,
    "max_positions": 1,
    "min_hold_days": 5,
    "cooldown_days": 1,
    "min_momentum": 0.0,
    "target_volatility": 0.60,
    "max_allocation_pct": 0.30,
    "max_portfolio_exposure": 0.90,
    "atr_sl_mult": 1.5,
    "trail_atr_mult": 2.0,
    "take_profit_atr_mult": 2.0,
    "take_profit_fraction": 0.50,
    "min_history_bars": 210,
    "min_dollar_volume": 5_000_000.0,
    "daily_max_drawdown_pct": 0.12,
    "flatten_on_drawdown": False,
    "peak_dd_trigger_pct": 0.10,
    "peak_dd_recover_pct": 0.04,
    "heat_size_mult": 0.50,
    "heat_max_positions": 1,
    "blowoff_rsi": 75.0,
    "blowoff_ema_extension": 0.30,
    "shock_lookback": 5,
    "shock_trigger_pct": -0.08,
    "shock_recover_pct": 0.0,
    "shock_trail_atr_mult": 1.0,
    "equity_lock_pct": 0.15,
    "lock_reclaim_rsi": 55.0,
    "slot_expand_rsi": 55.0,
    "rs_lookback": 14,
    "rotation_roc_edge": 0.05,
    "chop_roc_min": 0.0,
    "stop_pause_bars": 0,
    "late_cycle_buffer": 0.0,
    "regime_confirm_bars": 1,
    "btc_core": False,
    "macro_confirm_bars": 1,
    "drift_max_positions": 1,
    "drift_max_allocation_pct": 0.15,
    "loop_interval_sec": 60,
}

DEFAULT_STATE: dict[str, Any] = {
    "bot_running": False,
    "last_updated": None,
    "balance_usdt": None,
    "equity_usdt": None,
    "base_balance": None,
    "start_of_day_balance": None,
    "daily_drawdown_pct": 0.0,
    "trading_paused": False,
    "pause_reason": None,
    "last_processed_candle_ts": None,
    "cooldown_days_remaining": 0,
    "active_symbol": None,
    "active_symbols": [],
    "chart_symbol": universe.REGIME_SYMBOL,
    "regime": {},
    "rankings": [],
    "positions": [],
    "position": {
        "status": "flat",
        "symbol": None,
        "quantity": 0.0,
        "entry_price": None,
        "entry_time": None,
        "entry_bar_ts": None,
        "bars_held": 0,
        "stop_loss": None,
        "initial_stop": None,
        "trailing_stop": None,
        "highest_close": None,
        "entry_order_id": None,
        "protective_order_ids": [],
        "protection_status": None,
    },
    "drawdown_state": {"day": None, "start_equity": 0.0, "paused": False},
    "circuit": {
        "equity_peak": 0.0,
        "heat_active": False,
        "heat_drawdown_pct": 0.0,
        "market_shock": False,
        "blowoff": False,
        "btc_5d_return": None,
        "equity_lock": False,
        "all_time_peak": 0.0,
        "lock_drawdown_pct": 0.0,
    },
    "last_signal": None,
    "market": {},
    "candles": [],
    "operations": [],
    "logs": [],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return deepcopy(default)
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else deepcopy(default)
    except (json.JSONDecodeError, OSError):
        return deepcopy(default)


def _write_json_unlocked(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    temp.replace(path)


def _write_json(path: Path, data: dict) -> None:
    with _lock:
        _write_json_unlocked(path, data)


def ensure_settings_file() -> None:
    if not SETTINGS_FILE.exists():
        _write_json(SETTINGS_FILE, DEFAULT_SETTINGS)


def load_settings() -> dict[str, Any]:
    ensure_settings_file()
    stored = _read_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    merged = deepcopy(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in stored.items() if k in merged})
    return merged


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    allowed = set(DEFAULT_SETTINGS)
    for key, value in updates.items():
        if key in allowed:
            current[key] = value
    _write_json(SETTINGS_FILE, current)
    return current


def load_state() -> dict[str, Any]:
    stored = _read_json(STATE_FILE, DEFAULT_STATE)
    merged = deepcopy(DEFAULT_STATE)
    merged.update(stored)
    return merged


def update_state(**fields: Any) -> dict[str, Any]:
    with _lock:
        current = _read_json(STATE_FILE, DEFAULT_STATE)
        merged = deepcopy(DEFAULT_STATE)
        merged.update(current)
        merged.update(fields)
        merged["last_updated"] = _now_iso()
        _write_json_unlocked(STATE_FILE, merged)
        return merged


def append_log(message: str, level: str = "INFO") -> None:
    with _lock:
        current = _read_json(STATE_FILE, DEFAULT_STATE)
        merged = deepcopy(DEFAULT_STATE)
        merged.update(current)
        logs = merged.get("logs", [])
        logs.append({"time": _now_iso(), "level": level, "message": message})
        merged["logs"] = logs[-MAX_LOG_LINES:]
        merged["last_updated"] = _now_iso()
        _write_json_unlocked(STATE_FILE, merged)


def append_operation(op_type: str, detail: str, extra: dict[str, Any] | None = None) -> None:
    with _lock:
        current = _read_json(STATE_FILE, DEFAULT_STATE)
        merged = deepcopy(DEFAULT_STATE)
        merged.update(current)
        ops = merged.get("operations", [])
        entry: dict[str, Any] = {"time": _now_iso(), "type": op_type, "detail": detail}
        if extra:
            entry.update(extra)
        ops.insert(0, entry)
        merged["operations"] = ops[:MAX_OPERATIONS]
        merged["last_updated"] = _now_iso()
        _write_json_unlocked(STATE_FILE, merged)


def set_bot_running(running: bool) -> None:
    update_state(bot_running=running)
