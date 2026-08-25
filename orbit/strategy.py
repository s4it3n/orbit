"""Daily momentum rotation rules shared by live trading and backtesting.

Decision order on each completed daily bar:

1. Macro regime: BTC below its 200-day EMA forces cash.
2. Fast regime: BTC close ≤ 50-day EMA or RSI ≤ 50 blocks *all* new entries.
   Existing lots stay on trail / take-profit at full original size. The same
   block applies in chop, where BTC holds the 50-day EMA but sits below its
   20-day EMA or is flat-to-down over 14 days.
3. Equity lock: a 15% drop from the session all-time equity peak flattens
   everything. New entries stay blocked until BTC is back above its 50-day
   EMA with RSI > 55.
4. Blow-off: BTC RSI > 75 or price > 30% above its 50-day EMA blocks new alts.
5. Market shock: BTC 5-day return < -8% flattens to USDT at the next open and
   blocks all new buys until that 5-day return is back above 0%.
6. Drift defense: a negative 5-day BTC return that is still above -8% limits
   new entries to slot 1 at 15% equity. Existing slots 2/3 are not force-closed.
7. Eligibility: history and dollar-volume floors.
8. Per-coin trend: close must be above the coin's own trend EMA.
9. Rank: blended momentum / volatility, highest first.
10. Hold up to ``max_positions`` names from the top of that list, with
    hysteresis: a voluntary rank-drop rotation also needs the challenger to beat
    the held name by 5 percentage points of 14-day ROC.
11. Heat: a 10% drop from the in-market equity peak keeps only the best
    open lot, halves that lot to 15%, and blocks extra slots until equity
    is back within 4% of peak.
12. Capacity: a single slot (30% equity). Extra concurrent names were the
    source of initial-stop churn that turned otherwise-tradable halves negative.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Sequence

import pandas as pd

from . import config, data, universe

RANKING_FIELDS = (
    "close",
    "trend_ema",
    "fast_ema",
    "breadth_ema",
    "rsi",
    "roc_14",
    "fast_ema_slope",
    "fast_streak",
    "momentum",
    "volatility",
    "score",
    "atr",
    "dollar_volume",
    "bars_available",
)


@dataclass(frozen=True)
class RotationRules:
    rank_buffer: int = 3
    max_positions: int = 1
    min_hold_days: int = 5
    cooldown_days: int = 1
    min_momentum: float = 0.0
    target_volatility: float = 0.60
    max_allocation_pct: float = 0.30
    max_portfolio_exposure: float = 0.90
    atr_sl_mult: float = 1.5
    trail_atr_mult: float = 2.0
    take_profit_atr_mult: float = 2.0
    take_profit_fraction: float = 0.50
    rsi_threshold: float = 45.0
    full_capacity_rsi: float = 50.0
    defensive_size_mult: float = 0.50
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
    eligibility: universe.EligibilityRules = field(
        default_factory=universe.EligibilityRules
    )


@dataclass(frozen=True)
class AssetSnapshot:
    """One asset's completed-bar values, as consumed by the ranking."""

    symbol: str
    close: float = float("nan")
    trend_ema: float = float("nan")
    fast_ema: float = float("nan")
    breadth_ema: float = float("nan")
    rsi: float = float("nan")
    roc_14: float = float("nan")
    fast_ema_slope: float = float("nan")
    fast_streak: float = float("nan")
    momentum: float = float("nan")
    volatility: float = float("nan")
    score: float = float("nan")
    atr: float = float("nan")
    dollar_volume: float = float("nan")
    bars_available: float = float("nan")


@dataclass(frozen=True)
class Candidate:
    symbol: str
    score: float
    momentum: float
    volatility: float
    close: float
    atr: float
    qualified: bool
    reason: str | None
    rank: int | None
    roc_14: float = float("nan")
    fast_ema: float = float("nan")
    rsi: float = float("nan")


@dataclass(frozen=True)
class RegimeDecision:
    """Macro flatten vs fast block-new-entries, plus open-slot capacity."""

    macro_on: bool
    allow_new: bool
    reason: str
    defensive: bool = False
    max_open_slots: int = 0


@dataclass(frozen=True)
class BookAdjustment:
    """Exits and partial sells queued from this close for the next open."""

    exit_symbols: tuple[str, ...] = ()
    reductions: tuple[tuple[str, float, str], ...] = ()


@dataclass(frozen=True)
class EquityLock:
    """Session all-time equity peak and the 15% flatten-to-cash lock."""

    all_time_peak: float = 0.0
    lock_peak: float = 0.0
    drawdown: float = 0.0
    active: bool = False


@dataclass(frozen=True)
class HeatState:
    """Trailing in-market equity peak and the 10%/4% heat hysteresis."""

    peak_equity: float = 0.0
    drawdown: float = 0.0
    active: bool = False


def current_rules() -> RotationRules:
    return RotationRules(
        rank_buffer=config.RANK_BUFFER,
        max_positions=config.MAX_POSITIONS,
        min_hold_days=config.MIN_HOLD_DAYS,
        cooldown_days=config.COOLDOWN_DAYS,
        min_momentum=config.MIN_MOMENTUM,
        target_volatility=config.TARGET_VOLATILITY,
        max_allocation_pct=config.MAX_ALLOCATION_PCT,
        max_portfolio_exposure=config.MAX_PORTFOLIO_EXPOSURE,
        atr_sl_mult=config.ATR_SL_MULT,
        trail_atr_mult=config.TRAIL_ATR_MULT,
        take_profit_atr_mult=config.TAKE_PROFIT_ATR_MULT,
        take_profit_fraction=config.TAKE_PROFIT_FRACTION,
        rsi_threshold=config.RSI_THRESHOLD,
        full_capacity_rsi=config.FULL_CAPACITY_RSI,
        defensive_size_mult=config.DEFENSIVE_SIZE_MULT,
        peak_dd_trigger_pct=config.PEAK_DD_TRIGGER_PCT,
        peak_dd_recover_pct=config.PEAK_DD_RECOVER_PCT,
        heat_size_mult=config.HEAT_SIZE_MULT,
        heat_max_positions=config.HEAT_MAX_POSITIONS,
        blowoff_rsi=config.BLOWOFF_RSI,
        blowoff_ema_extension=config.BLOWOFF_EMA_EXTENSION,
        shock_lookback=config.SHOCK_LOOKBACK,
        shock_trigger_pct=config.SHOCK_TRIGGER_PCT,
        shock_recover_pct=config.SHOCK_RECOVER_PCT,
        shock_trail_atr_mult=config.SHOCK_TRAIL_ATR_MULT,
        equity_lock_pct=config.EQUITY_LOCK_PCT,
        lock_reclaim_rsi=config.LOCK_RECLAIM_RSI,
        slot_expand_rsi=config.SLOT_EXPAND_RSI,
        rs_lookback=config.RS_LOOKBACK,
        rotation_roc_edge=config.ROTATION_ROC_EDGE,
        chop_roc_min=config.CHOP_ROC_MIN,
        stop_pause_bars=config.STOP_PAUSE_BARS,
        late_cycle_buffer=config.LATE_CYCLE_BUFFER,
        regime_confirm_bars=config.REGIME_CONFIRM_BARS,
        btc_core=config.BTC_CORE,
        macro_confirm_bars=config.MACRO_CONFIRM_BARS,
        drift_max_positions=config.DRIFT_MAX_POSITIONS,
        drift_max_allocation_pct=config.DRIFT_MAX_ALLOCATION_PCT,
        eligibility=universe.EligibilityRules(
            min_history_bars=config.MIN_HISTORY_BARS,
            min_dollar_volume=config.MIN_DOLLAR_VOLUME,
        ),
    )


def rules_from_params(params: dict) -> RotationRules:
    """Build rules from a flat parameter dict (backtest configs, settings)."""
    base = RotationRules()
    return RotationRules(
        rank_buffer=int(params.get("rank_buffer", base.rank_buffer)),
        max_positions=int(params.get("max_positions", base.max_positions)),
        min_hold_days=int(params.get("min_hold_days", base.min_hold_days)),
        cooldown_days=int(params.get("cooldown_days", base.cooldown_days)),
        min_momentum=float(params.get("min_momentum", base.min_momentum)),
        target_volatility=float(
            params.get("target_volatility", base.target_volatility)
        ),
        max_allocation_pct=float(
            params.get("max_allocation_pct", base.max_allocation_pct)
        ),
        max_portfolio_exposure=float(
            params.get("max_portfolio_exposure", base.max_portfolio_exposure)
        ),
        atr_sl_mult=float(params.get("atr_sl_mult", base.atr_sl_mult)),
        trail_atr_mult=float(params.get("trail_atr_mult", base.trail_atr_mult)),
        take_profit_atr_mult=float(
            params.get("take_profit_atr_mult", base.take_profit_atr_mult)
        ),
        take_profit_fraction=float(
            params.get("take_profit_fraction", base.take_profit_fraction)
        ),
        rsi_threshold=float(params.get("rsi_threshold", base.rsi_threshold)),
        full_capacity_rsi=float(
            params.get("full_capacity_rsi", base.full_capacity_rsi)
        ),
        defensive_size_mult=float(
            params.get("defensive_size_mult", base.defensive_size_mult)
        ),
        peak_dd_trigger_pct=float(
            params.get("peak_dd_trigger_pct", base.peak_dd_trigger_pct)
        ),
        peak_dd_recover_pct=float(
            params.get("peak_dd_recover_pct", base.peak_dd_recover_pct)
        ),
        heat_size_mult=float(params.get("heat_size_mult", base.heat_size_mult)),
        heat_max_positions=int(
            params.get("heat_max_positions", base.heat_max_positions)
        ),
        blowoff_rsi=float(params.get("blowoff_rsi", base.blowoff_rsi)),
        blowoff_ema_extension=float(
            params.get("blowoff_ema_extension", base.blowoff_ema_extension)
        ),
        shock_lookback=int(params.get("shock_lookback", base.shock_lookback)),
        shock_trigger_pct=float(
            params.get("shock_trigger_pct", base.shock_trigger_pct)
        ),
        shock_recover_pct=float(
            params.get("shock_recover_pct", base.shock_recover_pct)
        ),
        shock_trail_atr_mult=float(
            params.get("shock_trail_atr_mult", base.shock_trail_atr_mult)
        ),
        equity_lock_pct=float(params.get("equity_lock_pct", base.equity_lock_pct)),
        lock_reclaim_rsi=float(params.get("lock_reclaim_rsi", base.lock_reclaim_rsi)),
        slot_expand_rsi=float(params.get("slot_expand_rsi", base.slot_expand_rsi)),
        rs_lookback=int(params.get("rs_lookback", base.rs_lookback)),
        rotation_roc_edge=float(
            params.get("rotation_roc_edge", base.rotation_roc_edge)
        ),
        chop_roc_min=float(params.get("chop_roc_min", base.chop_roc_min)),
        stop_pause_bars=int(params.get("stop_pause_bars", base.stop_pause_bars)),
        late_cycle_buffer=float(
            params.get("late_cycle_buffer", base.late_cycle_buffer)
        ),
        regime_confirm_bars=int(
            params.get("regime_confirm_bars", base.regime_confirm_bars)
        ),
        btc_core=bool(params.get("btc_core", base.btc_core)),
        macro_confirm_bars=int(
            params.get("macro_confirm_bars", base.macro_confirm_bars)
        ),
        drift_max_positions=int(
            params.get("drift_max_positions", base.drift_max_positions)
        ),
        drift_max_allocation_pct=float(
            params.get("drift_max_allocation_pct", base.drift_max_allocation_pct)
        ),
        eligibility=universe.EligibilityRules(
            min_history_bars=int(params.get("min_history_bars", 210)),
            min_dollar_volume=float(params.get("min_dollar_volume", 5_000_000.0)),
        ),
    )


def _finite(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def snapshot_from_series(symbol: str, row: pd.Series) -> AssetSnapshot:
    values = {name: float(row.get(name, float("nan"))) for name in RANKING_FIELDS}
    return AssetSnapshot(symbol=symbol, **values)


def snapshots_from_panel(panel: "data.Panel", index: int) -> list[AssetSnapshot]:
    rows = {name: panel.row(name, index) for name in RANKING_FIELDS if name in panel.data}
    out = []
    for position, symbol in enumerate(panel.symbols):
        kwargs = {name: float("nan") for name in RANKING_FIELDS}
        for name in rows:
            kwargs[name] = float(rows[name][position])
        out.append(AssetSnapshot(symbol=symbol, **kwargs))
    return out


def market_regime(snapshot: AssetSnapshot | None) -> tuple[bool, str]:
    """Macro risk switch only (BTC vs 200-day EMA)."""
    decision = evaluate_regime(snapshot)
    return decision.macro_on, decision.reason


def evaluate_regime(
    snapshot: AssetSnapshot | None,
    rules: RotationRules | None = None,
    *,
    previous: AssetSnapshot | None = None,
) -> RegimeDecision:
    """Macro flatten plus the 50-day / RSI new-entry lock."""
    rules = rules or current_rules()
    if snapshot is None:
        return RegimeDecision(False, False, "no regime data")
    if not _finite(snapshot.close) or not _finite(snapshot.trend_ema):
        return RegimeDecision(False, False, "regime warming up")
    if snapshot.close <= snapshot.trend_ema:
        confirmed = (
            rules.macro_confirm_bars < 2
            or (
                previous is not None
                and _finite(previous.close)
                and _finite(previous.trend_ema)
                and previous.close <= previous.trend_ema
            )
        )
        if confirmed:
            return RegimeDecision(False, False, "risk-off")
        return RegimeDecision(True, False, "macro-unconfirmed", defensive=True)

    if not _entry_unlocked(snapshot, rules):
        return RegimeDecision(True, False, _entry_block_reason(snapshot, rules), defensive=True)
    if rules.regime_confirm_bars >= 2 and not _entry_unlocked(previous, rules):
        return RegimeDecision(True, False, "unconfirmed", defensive=True)
    if is_late_cycle(snapshot, rules):
        return RegimeDecision(True, False, "late-cycle", defensive=True)
    return RegimeDecision(
        True, True, "risk-on", max_open_slots=rules.max_positions
    )


def _entry_unlocked(
    snapshot: AssetSnapshot | None,
    rules: RotationRules,
) -> bool:
    if snapshot is None:
        return False
    fast_on = _finite(snapshot.fast_ema) and snapshot.close > snapshot.fast_ema
    rsi_full = (not _finite(snapshot.rsi)) or snapshot.rsi > rules.full_capacity_rsi
    return fast_on and rsi_full and is_trend_clean(snapshot, rules)


def _entry_block_reason(snapshot: AssetSnapshot, rules: RotationRules) -> str:
    fast_on = _finite(snapshot.fast_ema) and snapshot.close > snapshot.fast_ema
    if not fast_on:
        return "fast-regime-off"
    rsi_full = (not _finite(snapshot.rsi)) or snapshot.rsi > rules.full_capacity_rsi
    if not rsi_full:
        return "rsi-weak"
    return "chop"


def is_late_cycle(
    snapshot: AssetSnapshot | None,
    rules: RotationRules | None = None,
) -> bool:
    """True when BTC is still above the 200-day EMA but too close to it to buy."""
    rules = rules or current_rules()
    if snapshot is None or rules.late_cycle_buffer <= 0:
        return False
    if not (_finite(snapshot.close) and _finite(snapshot.trend_ema)):
        return False
    if snapshot.trend_ema <= 0:
        return False
    return snapshot.close < snapshot.trend_ema * (1.0 + rules.late_cycle_buffer)


def is_trend_clean(
    snapshot: AssetSnapshot | None,
    rules: RotationRules | None = None,
) -> bool:
    """Chop filter: BTC has to be above its short EMA *and* up over 14 days.

    Sitting above the 50-day EMA is not enough — in post-rally chop BTC keeps
    crossing it while alt breakouts fail, and those are the entries that die on
    the initial stop. Warming-up indicators count as not clean.
    """
    rules = rules or current_rules()
    if snapshot is None:
        return False
    if not (_finite(snapshot.breadth_ema) and _finite(snapshot.close)):
        return False
    if snapshot.close <= snapshot.breadth_ema:
        return False
    return _finite(snapshot.roc_14) and snapshot.roc_14 > rules.chop_roc_min


def lookback_return(close_now: float, close_then: float) -> float:
    """``close / close[N bars ago] - 1``, or NaN if either print is unusable."""
    if not _finite(close_now) or not _finite(close_then) or close_then <= 0:
        return float("nan")
    return close_now / close_then - 1.0


def is_blowoff(
    snapshot: AssetSnapshot | None,
    rules: RotationRules | None = None,
) -> bool:
    """True when BTC is extended enough that new alt entries are refused."""
    rules = rules or current_rules()
    if snapshot is None:
        return False
    rsi_hot = _finite(snapshot.rsi) and snapshot.rsi > rules.blowoff_rsi
    extended = (
        _finite(snapshot.close)
        and _finite(snapshot.fast_ema)
        and snapshot.fast_ema > 0
        and (snapshot.close / snapshot.fast_ema - 1.0) > rules.blowoff_ema_extension
    )
    return bool(rsi_hot or extended)


def update_market_shock(
    previous: bool,
    btc_return: float,
    rules: RotationRules | None = None,
) -> bool:
    """Latch shock on a 5-day dump; flatten and block buys until return is positive."""
    rules = rules or current_rules()
    if not _finite(btc_return):
        return previous
    if btc_return < rules.shock_trigger_pct:
        return True
    if btc_return > rules.shock_recover_pct:
        return False
    return previous


def is_btc_drift(
    btc_return: float,
    rules: RotationRules | None = None,
) -> bool:
    """True when BTC's 5-day return is negative but still above the shock floor."""
    rules = rules or current_rules()
    if not _finite(btc_return):
        return False
    return rules.shock_trigger_pct < btc_return < rules.shock_recover_pct


def decay_stop_pause(remaining: int) -> int:
    return max(0, int(remaining) - 1)


def start_stop_pause(reason: str, rules: RotationRules | None = None) -> int:
    """Bars of blocked new entries after an initial stop, else 0."""
    rules = rules or current_rules()
    if str(reason or "") == "initial_stop":
        return max(0, int(rules.stop_pause_bars))
    return 0


def update_heat(
    previous: HeatState | None,
    equity: float,
    *,
    in_market: bool,
    rules: RotationRules | None = None,
) -> HeatState:
    """Ratchet the in-market equity peak and apply 10% / 4% hysteresis."""
    rules = rules or current_rules()
    prior = previous or HeatState()
    peak = prior.peak_equity
    if in_market and _finite(equity) and equity > 0:
        peak = max(peak, equity)
    elif peak <= 0 and _finite(equity) and equity > 0:
        peak = equity
    if peak <= 0 or not _finite(equity):
        return HeatState(peak_equity=peak, drawdown=0.0, active=prior.active)
    drawdown = max(0.0, (peak - equity) / peak)
    if prior.active:
        active = drawdown > rules.peak_dd_recover_pct
    else:
        active = drawdown >= rules.peak_dd_trigger_pct
    return HeatState(peak_equity=peak, drawdown=drawdown, active=active)


def btc_lock_reclaim(
    snapshot: AssetSnapshot | None,
    rules: RotationRules | None = None,
) -> bool:
    """True when BTC has reclaimed the 50-day EMA with RSI above the lock gate."""
    rules = rules or current_rules()
    if snapshot is None:
        return False
    if not (
        _finite(snapshot.close)
        and _finite(snapshot.fast_ema)
        and _finite(snapshot.rsi)
    ):
        return False
    return snapshot.close > snapshot.fast_ema and snapshot.rsi > rules.lock_reclaim_rsi


def update_equity_lock(
    previous: EquityLock | None,
    equity: float,
    *,
    reclaim: bool,
    rules: RotationRules | None = None,
) -> EquityLock:
    """Ratchet the session peak; latch a full flatten at −15% until BTC reclaims."""
    rules = rules or current_rules()
    prior = previous or EquityLock()
    if not _finite(equity) or equity <= 0:
        return prior
    all_time = max(prior.all_time_peak, equity)
    if prior.active:
        lock_peak = prior.lock_peak if prior.lock_peak > 0 else all_time
        drawdown = max(0.0, (lock_peak - equity) / lock_peak) if lock_peak > 0 else 0.0
        if reclaim:
            return EquityLock(
                all_time_peak=all_time,
                lock_peak=equity,
                drawdown=0.0,
                active=False,
            )
        return EquityLock(
            all_time_peak=all_time,
            lock_peak=lock_peak,
            drawdown=drawdown,
            active=True,
        )
    lock_peak = max(prior.lock_peak, equity)
    if lock_peak <= 0:
        lock_peak = equity
    drawdown = max(0.0, (lock_peak - equity) / lock_peak)
    active = drawdown >= rules.equity_lock_pct
    return EquityLock(
        all_time_peak=all_time,
        lock_peak=lock_peak,
        drawdown=drawdown,
        active=active,
    )


def entry_rules(
    rules: RotationRules,
    *,
    heat_active: bool,
    defensive: bool = False,
    max_open_slots: int | None = None,
    drift_active: bool = False,
) -> RotationRules:
    """Apply heat and 5-day drift caps. ``defensive`` is ignored."""
    del defensive
    cap = rules.max_positions
    allocation = rules.max_allocation_pct
    if max_open_slots is not None:
        cap = min(cap, max(0, int(max_open_slots)))
    if heat_active:
        cap = min(cap, rules.heat_max_positions)
        allocation = min(allocation, rules.max_allocation_pct * rules.heat_size_mult)
    if drift_active:
        cap = min(cap, rules.drift_max_positions)
        allocation = min(allocation, rules.drift_max_allocation_pct)
    if cap != rules.max_positions or allocation != rules.max_allocation_pct:
        return replace(rules, max_allocation_pct=allocation, max_positions=cap)
    return rules


def _excess_sell_fraction(notional: float, cap: float) -> float:
    if notional <= 0 or cap < 0 or notional <= cap:
        return 0.0
    return min(1.0, 1.0 - cap / notional)


def scale_fractions(
    notionals: dict[str, float],
    equity: float,
    *,
    slot_cap: float,
    gross_cap: float,
) -> dict[str, float]:
    """Per-symbol sell fraction so each lot ≤ slot_cap and gross ≤ gross_cap."""
    if equity <= 0 or not notionals:
        return {}
    slot_notional = slot_cap * equity
    remaining: dict[str, float] = {}
    sells: dict[str, float] = {}
    for symbol, notional in notionals.items():
        frac = _excess_sell_fraction(notional, slot_notional)
        sells[symbol] = frac
        remaining[symbol] = notional * (1.0 - frac)
    gross = sum(remaining.values())
    cap = gross_cap * equity
    if gross > cap and gross > 0:
        keep = cap / gross
        for symbol in remaining:
            sells[symbol] = 1.0 - (1.0 - sells[symbol]) * keep
    return {symbol: frac for symbol, frac in sells.items() if frac > 1e-9}


def book_adjustments(
    lots: Sequence[tuple[str, float, float]],
    *,
    equity: float,
    heat_active: bool,
    defensive: bool = False,
    rules: RotationRules | None = None,
    regime_symbol: str = "",
) -> BookAdjustment:
    """Heat keeps the best unrealized-PnL lot and cuts it to the 15% cap."""
    del defensive
    rules = rules or current_rules()
    remaining = list(lots)
    exit_symbols: list[str] = []
    if heat_active and len(remaining) > rules.heat_max_positions:
        if rules.btc_core and regime_symbol:
            core = [item for item in remaining if item[0] == regime_symbol]
            others = [item for item in remaining if item[0] != regime_symbol]
            if core:
                ranked = sorted(others, key=lambda item: item[2], reverse=True)
                keep_items = core[:1] + ranked[: max(0, rules.heat_max_positions - 1)]
            else:
                ranked = sorted(remaining, key=lambda item: item[2], reverse=True)
                keep_items = ranked[: rules.heat_max_positions]
        else:
            ranked = sorted(remaining, key=lambda item: item[2], reverse=True)
            keep_items = ranked[: rules.heat_max_positions]
        keep = {item[0] for item in keep_items}
        exit_symbols = [item[0] for item in remaining if item[0] not in keep]
        remaining = [item for item in remaining if item[0] in keep]
    if not remaining or not heat_active:
        return BookAdjustment(tuple(exit_symbols), ())
    sized = entry_rules(rules, heat_active=True)
    notionals = {symbol: notional for symbol, notional, _pnl in remaining}
    reductions = tuple(
        (symbol, frac, "heat_scale")
        for symbol, frac in scale_fractions(
            notionals,
            equity,
            slot_cap=sized.max_allocation_pct,
            gross_cap=sized.max_portfolio_exposure,
        ).items()
    )
    return BookAdjustment(tuple(exit_symbols), reductions)


def trail_multiple(rules: RotationRules, *, market_shock: bool) -> float:
    """Shock now flattens at the next open; trails stay at the standard multiple."""
    del market_shock
    return rules.trail_atr_mult


def select_new_entries(
    candidates: Sequence[Candidate],
    held_symbols: Sequence[str],
    rules: RotationRules | None = None,
    *,
    allow_new: bool,
    blowoff: bool,
    market_shock: bool,
    heat_active: bool,
    cooldown: bool,
    daily_loss_guard: bool,
    regime_symbol: str,
    defensive: bool = False,
    equity_lock: bool = False,
    max_open_slots: int | None = None,
    btc_5d_return: float = float("nan"),
    stop_pause: bool = False,
) -> tuple[list[Candidate], str | None]:
    """Picks for open slots, plus a skip reason when a slot stays empty."""
    rules = rules or current_rules()
    held = [symbol for symbol in held_symbols if symbol]
    if equity_lock:
        return [], "equity lock"
    if not allow_new:
        return [], "fast regime off"
    if market_shock:
        return [], "market shock"
    if cooldown:
        return [], "cooldown"
    if daily_loss_guard:
        return [], "daily loss guard"
    if stop_pause:
        return [], "stop pause"
    drift_active = is_btc_drift(btc_5d_return, rules)
    sized = entry_rules(
        rules,
        heat_active=heat_active,
        defensive=defensive,
        max_open_slots=max_open_slots,
        drift_active=drift_active,
    )
    picks = fill_open_slots(
        candidates, held, sized, regime_symbol=regime_symbol
    )
    if blowoff:
        blocked_alts = [item for item in picks if item.symbol != regime_symbol]
        picks = [item for item in picks if item.symbol == regime_symbol]
        if blocked_alts and not picks:
            return [], "blow-off"
    if picks:
        return picks, None
    if sized.max_positions < rules.max_positions and len(held) >= sized.max_positions:
        if heat_active:
            return [], "risk mitigation"
        if drift_active:
            return [], "drift defense"
    if len(held) < sized.max_positions:
        return [], "no qualifying asset"
    return [], None


def evaluate_candidates(
    snapshots: Sequence[AssetSnapshot],
    rules: RotationRules | None = None,
) -> list[Candidate]:
    """Gate every asset, then rank the survivors by score, best first."""
    rules = rules or current_rules()
    passing: list[Candidate] = []
    blocked: list[Candidate] = []

    for snapshot in snapshots:
        reason = _disqualify(snapshot, rules)
        candidate = Candidate(
            symbol=snapshot.symbol,
            score=snapshot.score,
            momentum=snapshot.momentum,
            volatility=snapshot.volatility,
            close=snapshot.close,
            atr=snapshot.atr,
            qualified=reason is None,
            reason=reason,
            rank=None,
            roc_14=snapshot.roc_14,
            fast_ema=snapshot.fast_ema,
            rsi=snapshot.rsi,
        )
        (passing if reason is None else blocked).append(candidate)

    passing.sort(key=lambda item: item.score, reverse=True)
    ranked = [
        replace(candidate, rank=position + 1)
        for position, candidate in enumerate(passing)
    ]
    blocked.sort(key=lambda item: item.symbol)
    return ranked + blocked


def _disqualify(snapshot: AssetSnapshot, rules: RotationRules) -> str | None:
    eligible, reason = universe.check_eligibility(
        bars_available=snapshot.bars_available,
        dollar_volume=snapshot.dollar_volume,
        rules=rules.eligibility,
    )
    if not eligible:
        return reason
    required = (
        snapshot.close,
        snapshot.trend_ema,
        snapshot.momentum,
        snapshot.volatility,
        snapshot.score,
        snapshot.atr,
    )
    if not all(_finite(value) for value in required):
        return "indicators warming up"
    if snapshot.volatility <= 0:
        return "no volatility"
    if snapshot.close <= snapshot.trend_ema:
        return "below trend"
    if snapshot.momentum <= rules.min_momentum:
        return "momentum not positive"
    return None


def qualified_candidates(candidates: Sequence[Candidate]) -> list[Candidate]:
    return [candidate for candidate in candidates if candidate.qualified]


def select_targets(
    candidates: Sequence[Candidate],
    rules: RotationRules | None = None,
) -> list[Candidate]:
    """Qualified names occupying the top ``max_positions`` ranks."""
    rules = rules or current_rules()
    return [
        candidate
        for candidate in candidates
        if candidate.qualified
        and candidate.rank is not None
        and candidate.rank <= rules.max_positions
    ]


def select_target(candidates: Sequence[Candidate]) -> Candidate | None:
    """Strongest qualifying asset (rank 1), or None."""
    for candidate in candidates:
        if candidate.qualified and candidate.rank == 1:
            return candidate
    return None


def fill_open_slots(
    candidates: Sequence[Candidate],
    held_symbols: Sequence[str],
    rules: RotationRules | None = None,
    *,
    regime_symbol: str = "",
) -> list[Candidate]:
    """Top-ranked names that are not already held, up to remaining slots."""
    rules = rules or current_rules()
    held = {symbol for symbol in held_symbols if symbol}
    room = max(0, rules.max_positions - len(held))
    if room == 0:
        return []
    picks: list[Candidate] = []
    if rules.btc_core and regime_symbol and regime_symbol not in held:
        core = find_candidate(candidates, regime_symbol)
        if core is not None and core.qualified:
            picks.append(core)
            held.add(regime_symbol)
    for candidate in select_targets(candidates, rules):
        if len(picks) >= room:
            break
        if candidate.symbol in held:
            continue
        picks.append(candidate)
        held.add(candidate.symbol)
    return picks[:room]


def find_candidate(
    candidates: Sequence[Candidate],
    symbol: str | None,
) -> Candidate | None:
    if not symbol:
        return None
    for candidate in candidates:
        if candidate.symbol == symbol:
            return candidate
    return None


def rotation_challenger(
    candidates: Sequence[Candidate],
    held_symbols: Sequence[str],
) -> Candidate | None:
    """Best qualifying name that is not already held — the would-be replacement."""
    held = {symbol for symbol in held_symbols if symbol}
    for candidate in candidates:
        if candidate.qualified and candidate.symbol not in held:
            return candidate
    return None


def rotation_edge_met(
    held: Candidate,
    candidates: Sequence[Candidate],
    held_symbols: Sequence[str],
    rules: RotationRules | None = None,
) -> bool:
    """Hysteresis: a swap needs a clear 14-day ROC edge, not a hair's breadth."""
    rules = rules or current_rules()
    challenger = rotation_challenger(candidates, held_symbols)
    if challenger is None:
        return False
    if not (_finite(challenger.roc_14) and _finite(held.roc_14)):
        return False
    return challenger.roc_14 > held.roc_14 + rules.rotation_roc_edge


def exit_reason(
    held_symbol: str,
    candidates: Sequence[Candidate],
    *,
    risk_on: bool,
    bars_held: int,
    rules: RotationRules | None = None,
    held_symbols: Sequence[str] = (),
    regime_symbol: str = "",
) -> str | None:
    """Why the held asset should be left, or None to keep holding.

    Macro risk-off and a broken own-trend exit immediately.
    Falling out of the top ``rank_buffer`` only rotates after ``min_hold_days``,
    and only when a non-held candidate clears the 14-day ROC hysteresis band.
    The fast regime does *not* force an exit — trailing stops manage those trades.
    """
    rules = rules or current_rules()
    if not risk_on:
        return "regime_risk_off"
    held = find_candidate(candidates, held_symbol)
    if held is None or not held.qualified:
        return "trend_exit"
    if bars_held < rules.min_hold_days:
        return None
    if rules.btc_core and regime_symbol and held_symbol == regime_symbol:
        return None
    if held.rank is not None and held.rank > rules.rank_buffer:
        book = [symbol for symbol in held_symbols if symbol] or [held_symbol]
        if rotation_edge_met(held, candidates, book, rules):
            return "rank_drop"
    return None


def allocation_fraction(
    volatility: float,
    rules: RotationRules | None = None,
) -> float:
    """Scale one slot so a calm coin and a wild coin carry similar risk."""
    rules = rules or current_rules()
    if not _finite(volatility) or volatility <= 0:
        return 0.0
    target = rules.target_volatility / volatility
    return max(0.0, min(target, rules.max_allocation_pct))


def position_size(
    equity: float,
    entry_price: float,
    volatility: float,
    rules: RotationRules | None = None,
) -> float:
    if equity <= 0 or entry_price <= 0:
        return 0.0
    fraction = allocation_fraction(volatility, rules)
    if fraction <= 0:
        return 0.0
    return round(equity * fraction / entry_price, 8)


def initial_stop_price(
    entry_price: float,
    atr: float,
    atr_sl_mult: float | None = None,
) -> float:
    multiple = config.ATR_SL_MULT if atr_sl_mult is None else atr_sl_mult
    return data.round_price(max(0.0, entry_price - multiple * atr))


def take_profit_price(
    entry_price: float,
    atr: float,
    take_profit_atr_mult: float | None = None,
) -> float:
    multiple = (
        config.TAKE_PROFIT_ATR_MULT
        if take_profit_atr_mult is None
        else take_profit_atr_mult
    )
    return data.round_price(entry_price + multiple * atr)


def update_trailing_stop(
    previous_stop: float,
    highest_close: float,
    latest_close: float,
    latest_atr: float,
    trail_atr_mult: float | None = None,
) -> tuple[float, float]:
    """Ratchet the stop up from the highest completed close; never lower it."""
    multiple = config.TRAIL_ATR_MULT if trail_atr_mult is None else trail_atr_mult
    new_highest = max(highest_close, latest_close)
    candidate = new_highest - multiple * latest_atr
    return data.round_price(max(previous_stop, candidate)), new_highest


@dataclass
class TradePlan:
    symbol: str
    quantity: float
    entry_price: float
    initial_stop: float
    take_profit: float
    allocation_pct: float
    volatility: float
    atr: float


def build_trade_plan(
    equity: float,
    candidate: Candidate,
    rules: RotationRules | None = None,
) -> TradePlan:
    rules = rules or current_rules()
    quantity = position_size(equity, candidate.close, candidate.volatility, rules)
    stop = initial_stop_price(candidate.close, candidate.atr, rules.atr_sl_mult)
    target = take_profit_price(
        candidate.close, candidate.atr, rules.take_profit_atr_mult
    )
    return TradePlan(
        symbol=candidate.symbol,
        quantity=quantity,
        entry_price=candidate.close,
        initial_stop=stop,
        take_profit=target,
        allocation_pct=allocation_fraction(candidate.volatility, rules),
        volatility=candidate.volatility,
        atr=candidate.atr,
    )


def _held_set(held: Sequence[str] | str | None) -> set[str]:
    if held is None:
        return set()
    if isinstance(held, str):
        return {held} if held else set()
    return {symbol for symbol in held if symbol}


def rankings_payload(
    candidates: Sequence[Candidate],
    held_symbol: Sequence[str] | str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Dashboard-friendly view of the ranking."""
    held = _held_set(held_symbol)
    rows = []
    for candidate in candidates:
        rows.append({
            "symbol": candidate.symbol,
            "rank": candidate.rank,
            "score": None if not _finite(candidate.score) else round(candidate.score, 4),
            "momentum_pct": (
                None if not _finite(candidate.momentum)
                else round(candidate.momentum * 100, 2)
            ),
            "volatility_pct": (
                None if not _finite(candidate.volatility)
                else round(candidate.volatility * 100, 1)
            ),
            "close": None if not _finite(candidate.close) else data.round_price(candidate.close),
            "qualified": candidate.qualified,
            "reason": candidate.reason,
            "held": candidate.symbol in held,
        })
    return rows if limit is None else rows[:limit]
