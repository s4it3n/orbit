"""Immutable backtest parameters for the daily rotation strategy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from orbit.universe import DEFAULT_UNIVERSE, REGIME_SYMBOL


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    fee_rate: float = 0.001
    slippage_bps: float = 5.0

    universe: tuple[str, ...] = DEFAULT_UNIVERSE
    regime_symbol: str = REGIME_SYMBOL

    # Ranking inputs
    trend_ema_period: int = 200
    fast_ema_period: int = 50
    breadth_ema_period: int = 20
    rsi_period: int = 14
    rsi_threshold: float = 45.0
    full_capacity_rsi: float = 50.0
    defensive_size_mult: float = 0.50
    momentum_lookbacks: tuple[int, ...] = (7, 14, 30)
    volatility_period: int = 30
    volume_lookback: int = 30
    atr_period: int = 14

    # Selection behaviour
    rank_buffer: int = 3
    max_positions: int = 1
    min_hold_days: int = 5
    cooldown_days: int = 1
    min_momentum: float = 0.0

    # Sizing and stops
    target_volatility: float = 0.60
    max_allocation_pct: float = 0.30
    max_portfolio_exposure: float = 0.90
    atr_sl_mult: float = 1.5
    trail_atr_mult: float = 2.0
    take_profit_atr_mult: float = 2.0
    take_profit_fraction: float = 0.50

    # Eligibility floors
    min_history_bars: int = 210
    min_dollar_volume: float = 5_000_000.0

    # Risk guards
    daily_max_drawdown_pct: float = 0.12
    peak_dd_trigger_pct: float = 0.10
    peak_dd_recover_pct: float = 0.04
    heat_size_mult: float = 0.50
    heat_max_positions: int = 1
    blowoff_rsi: float = 75.0
    blowoff_ema_extension: float = 0.30
    shock_lookback: int = 5
    shock_trigger_pct: float = -0.08
    shock_recover_pct: float = 0.0
    shock_trail_atr_mult: float = 1.0
    equity_lock_pct: float = 0.15
    lock_reclaim_rsi: float = 55.0
    slot_expand_rsi: float = 55.0
    rs_lookback: int = 14
    rotation_roc_edge: float = 0.05
    chop_roc_min: float = 0.0
    stop_pause_bars: int = 0
    late_cycle_buffer: float = 0.0
    regime_confirm_bars: int = 1
    btc_core: bool = False
    macro_confirm_bars: int = 1
    drift_max_positions: int = 1
    drift_max_allocation_pct: float = 0.15

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive.")
        if self.fee_rate < 0 or self.slippage_bps < 0:
            raise ValueError("Costs cannot be negative.")
        if self.trend_ema_period < 2:
            raise ValueError("trend_ema_period must be at least 2.")
        if self.fast_ema_period < 2:
            raise ValueError("fast_ema_period must be at least 2.")
        if self.breadth_ema_period < 2:
            raise ValueError("breadth_ema_period must be at least 2.")
        if self.rsi_period < 2:
            raise ValueError("rsi_period must be at least 2.")
        if not self.momentum_lookbacks or min(self.momentum_lookbacks) < 1:
            raise ValueError("momentum_lookbacks must be positive periods.")
        if self.volatility_period < 2:
            raise ValueError("volatility_period must be at least 2.")
        if self.atr_period < 2:
            raise ValueError("atr_period must be at least 2.")
        if self.rank_buffer < 1:
            raise ValueError("rank_buffer must be at least 1.")
        if self.max_positions < 1:
            raise ValueError("max_positions must be at least 1.")
        if self.min_hold_days < 0 or self.cooldown_days < 0:
            raise ValueError("Holding periods cannot be negative.")
        if self.target_volatility <= 0:
            raise ValueError("target_volatility must be positive.")
        if not 0 < self.max_allocation_pct <= 1:
            raise ValueError("max_allocation_pct must be within (0, 1].")
        if not 0 < self.max_portfolio_exposure <= 1:
            raise ValueError("max_portfolio_exposure must be within (0, 1].")
        if self.atr_sl_mult <= 0 or self.trail_atr_mult <= 0:
            raise ValueError("ATR multiples must be positive.")
        if self.take_profit_atr_mult <= 0:
            raise ValueError("take_profit_atr_mult must be positive.")
        if not 0 < self.take_profit_fraction <= 1:
            raise ValueError("take_profit_fraction must be within (0, 1].")
        if self.min_history_bars < self.trend_ema_period:
            raise ValueError(
                "min_history_bars must cover trend_ema_period so the trend "
                "filter is defined before an asset can be ranked."
            )
        if not 0 < self.daily_max_drawdown_pct < 1:
            raise ValueError("daily_max_drawdown_pct must be within (0, 1).")
        if not 0 < self.peak_dd_trigger_pct < 1:
            raise ValueError("peak_dd_trigger_pct must be within (0, 1).")
        if not 0 <= self.peak_dd_recover_pct < self.peak_dd_trigger_pct:
            raise ValueError(
                "peak_dd_recover_pct must be in [0, peak_dd_trigger_pct)."
            )
        if not 0 < self.heat_size_mult <= 1:
            raise ValueError("heat_size_mult must be within (0, 1].")
        if not 0 < self.defensive_size_mult <= 1:
            raise ValueError("defensive_size_mult must be within (0, 1].")
        if not 0 < self.full_capacity_rsi <= 100:
            raise ValueError("full_capacity_rsi must be within (0, 100].")
        if self.heat_max_positions < 1:
            raise ValueError("heat_max_positions must be at least 1.")
        if not 0 < self.blowoff_rsi <= 100:
            raise ValueError("blowoff_rsi must be within (0, 100].")
        if self.blowoff_ema_extension <= 0:
            raise ValueError("blowoff_ema_extension must be positive.")
        if self.shock_lookback < 1:
            raise ValueError("shock_lookback must be at least 1.")
        if self.shock_trigger_pct >= 0:
            raise ValueError("shock_trigger_pct must be negative.")
        if self.shock_trail_atr_mult <= 0:
            raise ValueError("shock_trail_atr_mult must be positive.")
        if not 0 < self.equity_lock_pct < 1:
            raise ValueError("equity_lock_pct must be within (0, 1).")
        if not 0 < self.lock_reclaim_rsi <= 100:
            raise ValueError("lock_reclaim_rsi must be within (0, 100].")
        if not 0 < self.slot_expand_rsi <= 100:
            raise ValueError("slot_expand_rsi must be within (0, 100].")
        if self.rs_lookback < 1:
            raise ValueError("rs_lookback must be at least 1.")
        if self.rotation_roc_edge < 0:
            raise ValueError("rotation_roc_edge must be non-negative.")
        if self.stop_pause_bars < 0:
            raise ValueError("stop_pause_bars must be non-negative.")
        if self.late_cycle_buffer < 0:
            raise ValueError("late_cycle_buffer must be non-negative.")
        if self.regime_confirm_bars < 1:
            raise ValueError("regime_confirm_bars must be at least 1.")
        if self.macro_confirm_bars < 1:
            raise ValueError("macro_confirm_bars must be at least 1.")
        if self.drift_max_positions < 0:
            raise ValueError("drift_max_positions must be non-negative.")
        if not 0 < self.drift_max_allocation_pct <= 1:
            raise ValueError("drift_max_allocation_pct must be within (0, 1].")

    def with_costs(self, fee_rate: float, slippage_bps: float) -> "BacktestConfig":
        return replace(self, fee_rate=fee_rate, slippage_bps=slippage_bps)

    def indicator_params(self) -> dict[str, Any]:
        """Keyword arguments for :func:`data.add_indicators`."""
        return {
            "trend_ema_period": self.trend_ema_period,
            "fast_ema_period": self.fast_ema_period,
            "breadth_ema_period": self.breadth_ema_period,
            "rsi_period": self.rsi_period,
            "momentum_lookbacks": tuple(self.momentum_lookbacks),
            "volatility_period": self.volatility_period,
            "atr_period": self.atr_period,
            "volume_lookback": self.volume_lookback,
        }

    def rotation_params(self) -> dict[str, Any]:
        """Keyword arguments for :func:`strategy.rules_from_params`."""
        return {
            "rank_buffer": self.rank_buffer,
            "max_positions": self.max_positions,
            "min_hold_days": self.min_hold_days,
            "cooldown_days": self.cooldown_days,
            "min_momentum": self.min_momentum,
            "target_volatility": self.target_volatility,
            "max_allocation_pct": self.max_allocation_pct,
            "max_portfolio_exposure": self.max_portfolio_exposure,
            "atr_sl_mult": self.atr_sl_mult,
            "trail_atr_mult": self.trail_atr_mult,
            "take_profit_atr_mult": self.take_profit_atr_mult,
            "take_profit_fraction": self.take_profit_fraction,
            "rsi_threshold": self.rsi_threshold,
            "full_capacity_rsi": self.full_capacity_rsi,
            "defensive_size_mult": self.defensive_size_mult,
            "peak_dd_trigger_pct": self.peak_dd_trigger_pct,
            "peak_dd_recover_pct": self.peak_dd_recover_pct,
            "heat_size_mult": self.heat_size_mult,
            "heat_max_positions": self.heat_max_positions,
            "blowoff_rsi": self.blowoff_rsi,
            "blowoff_ema_extension": self.blowoff_ema_extension,
            "shock_lookback": self.shock_lookback,
            "shock_trigger_pct": self.shock_trigger_pct,
            "shock_recover_pct": self.shock_recover_pct,
            "shock_trail_atr_mult": self.shock_trail_atr_mult,
            "equity_lock_pct": self.equity_lock_pct,
            "lock_reclaim_rsi": self.lock_reclaim_rsi,
            "slot_expand_rsi": self.slot_expand_rsi,
            "rs_lookback": self.rs_lookback,
            "rotation_roc_edge": self.rotation_roc_edge,
            "chop_roc_min": self.chop_roc_min,
            "stop_pause_bars": self.stop_pause_bars,
            "late_cycle_buffer": self.late_cycle_buffer,
            "regime_confirm_bars": self.regime_confirm_bars,
            "btc_core": self.btc_core,
            "macro_confirm_bars": self.macro_confirm_bars,
            "drift_max_positions": self.drift_max_positions,
            "drift_max_allocation_pct": self.drift_max_allocation_pct,
            "min_history_bars": self.min_history_bars,
            "min_dollar_volume": self.min_dollar_volume,
        }
