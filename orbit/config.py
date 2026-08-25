"""Orbit configuration: secrets from .env, strategy from settings.json."""

from __future__ import annotations

import os

import ccxt
from dotenv import load_dotenv

from . import state, universe

load_dotenv()

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Authenticated sandbox for paper orders.
exchange: ccxt.binance = ccxt.binance({
    "apiKey": BINANCE_API_KEY,
    "secret": BINANCE_SECRET_KEY,
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot",
        "adjustForTimeDifference": True,
        "recvWindow": 60000,
    },
})
exchange.set_sandbox_mode(True)

# Public mainnet — charts and backtests need real history (testnet has almost none).
public_exchange: ccxt.binance = ccxt.binance({"enableRateLimit": True})

BOT_ENABLED = False
UNIVERSE: tuple[str, ...] = universe.DEFAULT_UNIVERSE
REGIME_SYMBOL = universe.REGIME_SYMBOL
TIMEFRAME = "1d"
TREND_EMA_PERIOD = 200
FAST_EMA_PERIOD = 50
BREADTH_EMA_PERIOD = 20
RSI_PERIOD = 14
RSI_THRESHOLD = 45.0
FULL_CAPACITY_RSI = 50.0
DEFENSIVE_SIZE_MULT = 0.50
MOMENTUM_LOOKBACKS: tuple[int, ...] = (7, 14, 30)
VOLATILITY_PERIOD = 30
VOLUME_LOOKBACK = 30
ATR_PERIOD = 14
RANK_BUFFER = 3
MAX_POSITIONS = 1
MIN_HOLD_DAYS = 5
COOLDOWN_DAYS = 1
MIN_MOMENTUM = 0.0
TARGET_VOLATILITY = 0.60
MAX_ALLOCATION_PCT = 0.30
MAX_PORTFOLIO_EXPOSURE = 0.90
ATR_SL_MULT = 1.5
TRAIL_ATR_MULT = 2.0
TAKE_PROFIT_ATR_MULT = 2.0
TAKE_PROFIT_FRACTION = 0.50
MIN_HISTORY_BARS = 210
MIN_DOLLAR_VOLUME = 5_000_000.0
DAILY_MAX_DRAWDOWN_PCT = 0.12
FLATTEN_ON_DRAWDOWN = False
PEAK_DD_TRIGGER_PCT = 0.10
PEAK_DD_RECOVER_PCT = 0.04
HEAT_SIZE_MULT = 0.50
HEAT_MAX_POSITIONS = 1
BLOWOFF_RSI = 75.0
BLOWOFF_EMA_EXTENSION = 0.30
SHOCK_LOOKBACK = 5
SHOCK_TRIGGER_PCT = -0.08
SHOCK_RECOVER_PCT = 0.0
SHOCK_TRAIL_ATR_MULT = 1.0
EQUITY_LOCK_PCT = 0.15
LOCK_RECLAIM_RSI = 55.0
SLOT_EXPAND_RSI = 55.0
RS_LOOKBACK = 14
ROTATION_ROC_EDGE = 0.05
CHOP_ROC_MIN = 0.0
STOP_PAUSE_BARS = 0
LATE_CYCLE_BUFFER = 0.0
REGIME_CONFIRM_BARS = 1
BTC_CORE = False
MACRO_CONFIRM_BARS = 1
DRIFT_MAX_POSITIONS = 1
DRIFT_MAX_ALLOCATION_PCT = 0.15
CANDLE_LIMIT = 400
LOOP_INTERVAL_SEC = 60


def _parse_lookbacks(value: object) -> tuple[int, ...]:
    if isinstance(value, str):
        parts = [p for p in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        return MOMENTUM_LOOKBACKS
    periods = sorted({int(float(str(p).strip())) for p in parts if str(p).strip()})
    valid = tuple(p for p in periods if p > 0)
    return valid or MOMENTUM_LOOKBACKS


def reload_settings() -> None:
    global BOT_ENABLED, UNIVERSE, TIMEFRAME, TREND_EMA_PERIOD, FAST_EMA_PERIOD
    global RSI_PERIOD, RSI_THRESHOLD, MOMENTUM_LOOKBACKS
    global FULL_CAPACITY_RSI, DEFENSIVE_SIZE_MULT, BREADTH_EMA_PERIOD
    global VOLATILITY_PERIOD, VOLUME_LOOKBACK, ATR_PERIOD, RANK_BUFFER
    global MAX_POSITIONS, MIN_HOLD_DAYS, COOLDOWN_DAYS, MIN_MOMENTUM
    global TARGET_VOLATILITY, MAX_ALLOCATION_PCT, MAX_PORTFOLIO_EXPOSURE
    global ATR_SL_MULT, TRAIL_ATR_MULT, TAKE_PROFIT_ATR_MULT, TAKE_PROFIT_FRACTION
    global MIN_HISTORY_BARS, MIN_DOLLAR_VOLUME, DAILY_MAX_DRAWDOWN_PCT
    global FLATTEN_ON_DRAWDOWN, LOOP_INTERVAL_SEC
    global PEAK_DD_TRIGGER_PCT, PEAK_DD_RECOVER_PCT, HEAT_SIZE_MULT
    global HEAT_MAX_POSITIONS, BLOWOFF_RSI, BLOWOFF_EMA_EXTENSION
    global SHOCK_LOOKBACK, SHOCK_TRIGGER_PCT, SHOCK_RECOVER_PCT
    global SHOCK_TRAIL_ATR_MULT, EQUITY_LOCK_PCT, LOCK_RECLAIM_RSI
    global SLOT_EXPAND_RSI, RS_LOOKBACK, ROTATION_ROC_EDGE, CHOP_ROC_MIN
    global STOP_PAUSE_BARS, LATE_CYCLE_BUFFER, REGIME_CONFIRM_BARS
    global BTC_CORE, MACRO_CONFIRM_BARS
    global DRIFT_MAX_POSITIONS, DRIFT_MAX_ALLOCATION_PCT

    s = state.load_settings()
    BOT_ENABLED = bool(s["bot_enabled"])
    UNIVERSE = universe.parse_universe(s["universe"])
    TIMEFRAME = str(s["timeframe"])
    TREND_EMA_PERIOD = int(s["trend_ema_period"])
    FAST_EMA_PERIOD = int(s.get("fast_ema_period", FAST_EMA_PERIOD))
    BREADTH_EMA_PERIOD = int(s.get("breadth_ema_period", BREADTH_EMA_PERIOD))
    RSI_PERIOD = int(s.get("rsi_period", RSI_PERIOD))
    RSI_THRESHOLD = float(s.get("rsi_threshold", RSI_THRESHOLD))
    FULL_CAPACITY_RSI = float(s.get("full_capacity_rsi", FULL_CAPACITY_RSI))
    DEFENSIVE_SIZE_MULT = float(s.get("defensive_size_mult", DEFENSIVE_SIZE_MULT))
    MOMENTUM_LOOKBACKS = _parse_lookbacks(s["momentum_lookbacks"])
    VOLATILITY_PERIOD = int(s["volatility_period"])
    VOLUME_LOOKBACK = int(s["volume_lookback"])
    ATR_PERIOD = int(s["atr_period"])
    RANK_BUFFER = int(s["rank_buffer"])
    MAX_POSITIONS = int(s.get("max_positions", MAX_POSITIONS))
    MIN_HOLD_DAYS = int(s["min_hold_days"])
    COOLDOWN_DAYS = int(s["cooldown_days"])
    MIN_MOMENTUM = float(s["min_momentum"])
    TARGET_VOLATILITY = float(s["target_volatility"])
    MAX_ALLOCATION_PCT = float(s["max_allocation_pct"])
    MAX_PORTFOLIO_EXPOSURE = float(s.get("max_portfolio_exposure", MAX_PORTFOLIO_EXPOSURE))
    ATR_SL_MULT = float(s["atr_sl_mult"])
    TRAIL_ATR_MULT = float(s["trail_atr_mult"])
    TAKE_PROFIT_ATR_MULT = float(s.get("take_profit_atr_mult", TAKE_PROFIT_ATR_MULT))
    TAKE_PROFIT_FRACTION = float(s.get("take_profit_fraction", TAKE_PROFIT_FRACTION))
    MIN_HISTORY_BARS = int(s["min_history_bars"])
    MIN_DOLLAR_VOLUME = float(s["min_dollar_volume"])
    DAILY_MAX_DRAWDOWN_PCT = float(s["daily_max_drawdown_pct"])
    FLATTEN_ON_DRAWDOWN = bool(s["flatten_on_drawdown"])
    PEAK_DD_TRIGGER_PCT = float(s.get("peak_dd_trigger_pct", PEAK_DD_TRIGGER_PCT))
    PEAK_DD_RECOVER_PCT = float(s.get("peak_dd_recover_pct", PEAK_DD_RECOVER_PCT))
    HEAT_SIZE_MULT = float(s.get("heat_size_mult", HEAT_SIZE_MULT))
    HEAT_MAX_POSITIONS = int(s.get("heat_max_positions", HEAT_MAX_POSITIONS))
    BLOWOFF_RSI = float(s.get("blowoff_rsi", BLOWOFF_RSI))
    BLOWOFF_EMA_EXTENSION = float(s.get("blowoff_ema_extension", BLOWOFF_EMA_EXTENSION))
    SHOCK_LOOKBACK = int(s.get("shock_lookback", SHOCK_LOOKBACK))
    SHOCK_TRIGGER_PCT = float(s.get("shock_trigger_pct", SHOCK_TRIGGER_PCT))
    SHOCK_RECOVER_PCT = float(s.get("shock_recover_pct", SHOCK_RECOVER_PCT))
    SHOCK_TRAIL_ATR_MULT = float(s.get("shock_trail_atr_mult", SHOCK_TRAIL_ATR_MULT))
    EQUITY_LOCK_PCT = float(s.get("equity_lock_pct", EQUITY_LOCK_PCT))
    LOCK_RECLAIM_RSI = float(s.get("lock_reclaim_rsi", LOCK_RECLAIM_RSI))
    SLOT_EXPAND_RSI = float(s.get("slot_expand_rsi", SLOT_EXPAND_RSI))
    RS_LOOKBACK = int(s.get("rs_lookback", RS_LOOKBACK))
    ROTATION_ROC_EDGE = float(s.get("rotation_roc_edge", ROTATION_ROC_EDGE))
    CHOP_ROC_MIN = float(s.get("chop_roc_min", CHOP_ROC_MIN))
    STOP_PAUSE_BARS = int(s.get("stop_pause_bars", STOP_PAUSE_BARS))
    LATE_CYCLE_BUFFER = float(s.get("late_cycle_buffer", LATE_CYCLE_BUFFER))
    REGIME_CONFIRM_BARS = int(s.get("regime_confirm_bars", REGIME_CONFIRM_BARS))
    BTC_CORE = bool(s.get("btc_core", BTC_CORE))
    MACRO_CONFIRM_BARS = int(s.get("macro_confirm_bars", MACRO_CONFIRM_BARS))
    DRIFT_MAX_POSITIONS = int(s.get("drift_max_positions", DRIFT_MAX_POSITIONS))
    DRIFT_MAX_ALLOCATION_PCT = float(
        s.get("drift_max_allocation_pct", DRIFT_MAX_ALLOCATION_PCT)
    )
    LOOP_INTERVAL_SEC = int(s["loop_interval_sec"])


def get_strategy_params() -> dict[str, object]:
    return {
        "trend_ema_period": TREND_EMA_PERIOD,
        "fast_ema_period": FAST_EMA_PERIOD,
        "breadth_ema_period": BREADTH_EMA_PERIOD,
        "rsi_period": RSI_PERIOD,
        "rsi_threshold": RSI_THRESHOLD,
        "full_capacity_rsi": FULL_CAPACITY_RSI,
        "defensive_size_mult": DEFENSIVE_SIZE_MULT,
        "momentum_lookbacks": tuple(MOMENTUM_LOOKBACKS),
        "volatility_period": VOLATILITY_PERIOD,
        "volume_lookback": VOLUME_LOOKBACK,
        "atr_period": ATR_PERIOD,
        "rank_buffer": RANK_BUFFER,
        "max_positions": MAX_POSITIONS,
        "min_hold_days": MIN_HOLD_DAYS,
        "cooldown_days": COOLDOWN_DAYS,
        "min_momentum": MIN_MOMENTUM,
        "target_volatility": TARGET_VOLATILITY,
        "max_allocation_pct": MAX_ALLOCATION_PCT,
        "max_portfolio_exposure": MAX_PORTFOLIO_EXPOSURE,
        "atr_sl_mult": ATR_SL_MULT,
        "trail_atr_mult": TRAIL_ATR_MULT,
        "take_profit_atr_mult": TAKE_PROFIT_ATR_MULT,
        "take_profit_fraction": TAKE_PROFIT_FRACTION,
        "min_history_bars": MIN_HISTORY_BARS,
        "min_dollar_volume": MIN_DOLLAR_VOLUME,
        "daily_max_drawdown_pct": DAILY_MAX_DRAWDOWN_PCT,
        "peak_dd_trigger_pct": PEAK_DD_TRIGGER_PCT,
        "peak_dd_recover_pct": PEAK_DD_RECOVER_PCT,
        "heat_size_mult": HEAT_SIZE_MULT,
        "heat_max_positions": HEAT_MAX_POSITIONS,
        "blowoff_rsi": BLOWOFF_RSI,
        "blowoff_ema_extension": BLOWOFF_EMA_EXTENSION,
        "shock_lookback": SHOCK_LOOKBACK,
        "shock_trigger_pct": SHOCK_TRIGGER_PCT,
        "shock_recover_pct": SHOCK_RECOVER_PCT,
        "shock_trail_atr_mult": SHOCK_TRAIL_ATR_MULT,
        "equity_lock_pct": EQUITY_LOCK_PCT,
        "lock_reclaim_rsi": LOCK_RECLAIM_RSI,
        "slot_expand_rsi": SLOT_EXPAND_RSI,
        "rs_lookback": RS_LOOKBACK,
        "rotation_roc_edge": ROTATION_ROC_EDGE,
        "chop_roc_min": CHOP_ROC_MIN,
        "stop_pause_bars": STOP_PAUSE_BARS,
        "late_cycle_buffer": LATE_CYCLE_BUFFER,
        "regime_confirm_bars": REGIME_CONFIRM_BARS,
        "btc_core": BTC_CORE,
        "macro_confirm_bars": MACRO_CONFIRM_BARS,
        "drift_max_positions": DRIFT_MAX_POSITIONS,
        "drift_max_allocation_pct": DRIFT_MAX_ALLOCATION_PCT,
    }


state.ensure_settings_file()
reload_settings()
