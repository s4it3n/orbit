"""Bar-by-bar daily rotation simulator.

Per bar the order of operations is fixed and deliberate:

1. Fill orders queued on the previous close, at this bar's open.
2. Check each stop, which was fixed on an earlier close, against this bar's low.
3. Scale out 50% if this bar's high reaches the take-profit.
4. Mark the book to this bar's close and record equity.
5. Apply the outsized-loss guard.
6. Rank on this bar's close and queue any order for the *next* open.
7. Ratchet trailing stops from this bar's close.

Nothing in step 6 can influence steps 1-5 of the same bar, which is what makes
the simulation free of lookahead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from orbit import data, strategy

from .config import BacktestConfig

# exit_reason() speaks in rule terms; trade records use trade terms.
_EXIT_LABELS = {
    "rank_drop": "rotation",
    "trend_exit": "trend_exit",
    "regime_risk_off": "regime_risk_off",
    "heat": "heat",
    "equity_lock": "equity_lock",
    "market_shock": "market_shock",
}


@dataclass
class BacktestResult:
    initial_capital: float
    final_equity: float
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    skipped_signals: dict[str, int] = field(default_factory=dict)
    fees_paid: float = 0.0
    rotations: int = 0
    cash_bars: int = 0
    bars: int = 0


@dataclass
class _Lot:
    symbol: str
    idx: int
    qty: float
    entry_price: float
    entry_cost: float
    entry_time: object
    initial_stop: float
    active_stop: float
    highest_close: float
    bars_held: int
    take_profit: float
    entry_atr: float = float("nan")
    tp_taken: bool = False


def _ok(value: float) -> bool:
    """True when a panel cell holds a usable number (not NaN, not infinite)."""
    return math.isfinite(value)


def _panel_value(store: dict, name: str, index: int, position: int) -> float:
    array = store.get(name)
    if array is None:
        return float("nan")
    return float(array[index][position])


def run_backtest(panel: data.Panel, cfg: BacktestConfig) -> BacktestResult:
    """Simulate the rotation over an aligned multi-symbol daily panel."""
    rules = strategy.rules_from_params(cfg.rotation_params())
    slip = cfg.slippage_bps / 10_000.0
    dates = panel.dates

    opens = panel.data["open"]
    highs = panel.data["high"]
    lows = panel.data["low"]
    closes = panel.data["close"]
    atrs = panel.data["atr"]

    tradable = tuple(symbol for symbol in cfg.universe if symbol in panel.symbols)
    if not tradable:
        raise ValueError("None of the configured universe is present in the panel.")
    positions = {symbol: panel.index_of(symbol) for symbol in tradable}
    regime_position = (
        panel.index_of(cfg.regime_symbol)
        if cfg.regime_symbol in panel.symbols
        else None
    )

    result = BacktestResult(
        initial_capital=cfg.initial_capital,
        final_equity=cfg.initial_capital,
    )

    cash = cfg.initial_capital
    lots: list[_Lot] = []
    cooldown = 0
    loss_guard_bars = 0
    previous_equity: float | None = None
    pending_exits: dict[str, str] = {}
    pending_reductions: dict[str, tuple[float, str]] = {}
    pending_entries: list[tuple[str, int, float, float, float, float]] = []
    heat = strategy.HeatState(peak_equity=cfg.initial_capital)
    equity_lock = strategy.EquityLock(
        all_time_peak=cfg.initial_capital,
        lock_peak=cfg.initial_capital,
    )
    market_shock = False
    stop_pause = 0
    previous_regime_snapshot = None

    def skip(reason: str) -> None:
        result.skipped_signals[reason] = result.skipped_signals.get(reason, 0) + 1

    def held_symbols() -> list[str]:
        return [lot.symbol for lot in lots]

    def mark_lot(lot: _Lot, index: int) -> float:
        raw = closes[index][lot.idx]
        if _ok(raw) and raw > 0:
            return float(raw)
        return lot.entry_price

    def deployed_notional(index: int) -> float:
        total = 0.0
        for lot in lots:
            raw = opens[index][lot.idx]
            price = float(raw) if _ok(raw) and raw > 0 else lot.entry_price
            total += lot.qty * price
        return total

    def close_lot(lot: _Lot, price: float, reason: str, timestamp: object) -> None:
        nonlocal cash, stop_pause
        proceeds = lot.qty * price
        fee = proceeds * cfg.fee_rate
        cash += proceeds - fee
        result.fees_paid += fee
        pnl = proceeds - fee - lot.entry_cost
        result.trades.append({
            "symbol": lot.symbol,
            "entry_time": lot.entry_time,
            "exit_time": timestamp,
            "entry_price": lot.entry_price,
            "exit_price": price,
            "quantity": lot.qty,
            "pnl_usdt": pnl,
            "return_pct": pnl / max(lot.entry_cost, 1e-12) * 100,
            "reason": reason,
            "bars_held": lot.bars_held,
        })
        pause = strategy.start_stop_pause(reason, rules)
        if pause > stop_pause:
            stop_pause = pause
        lots.remove(lot)

    def reduce_lot(
        lot: _Lot,
        price: float,
        fraction: float,
        timestamp: object,
        reason: str = "take_profit",
    ) -> None:
        nonlocal cash
        sell_qty = lot.qty * fraction
        if sell_qty <= 0 or sell_qty >= lot.qty:
            close_lot(lot, price, reason, timestamp)
            return
        sold_cost = lot.entry_cost * (sell_qty / lot.qty)
        proceeds = sell_qty * price
        fee = proceeds * cfg.fee_rate
        cash += proceeds - fee
        result.fees_paid += fee
        pnl = proceeds - fee - sold_cost
        result.trades.append({
            "symbol": lot.symbol,
            "entry_time": lot.entry_time,
            "exit_time": timestamp,
            "entry_price": lot.entry_price,
            "exit_price": price,
            "quantity": sell_qty,
            "pnl_usdt": pnl,
            "return_pct": pnl / max(sold_cost, 1e-12) * 100,
            "reason": reason,
            "bars_held": lot.bars_held,
        })
        lot.qty -= sell_qty
        lot.entry_cost -= sold_cost
        if reason == "take_profit":
            lot.tp_taken = True

    for index in range(len(dates)):
        timestamp = dates[index]
        stop_pause = strategy.decay_stop_pause(stop_pause)

        # 1. Orders queued on the previous close fill at this open.
        for symbol, reason in list(pending_exits.items()):
            lot = next((item for item in lots if item.symbol == symbol), None)
            if lot is None:
                pending_exits.pop(symbol, None)
                continue
            raw = opens[index][lot.idx]
            if not _ok(raw):
                raw = closes[index][lot.idx]
            if _ok(raw) and raw > 0:
                close_lot(lot, raw * (1 - slip), _EXIT_LABELS.get(reason, reason), timestamp)
                pending_exits.pop(symbol, None)
                pending_reductions.pop(symbol, None)

        for symbol, (fraction, reason) in list(pending_reductions.items()):
            lot = next((item for item in lots if item.symbol == symbol), None)
            pending_reductions.pop(symbol, None)
            if lot is None or fraction <= 0:
                continue
            raw = opens[index][lot.idx]
            if not _ok(raw):
                raw = closes[index][lot.idx]
            if _ok(raw) and raw > 0:
                reduce_lot(lot, raw * (1 - slip), fraction, timestamp, reason)

        for symbol, position, volatility, signal_atr, max_alloc, max_gross in pending_entries:
            if any(lot.symbol == symbol for lot in lots):
                continue
            if len(lots) >= rules.max_positions:
                skip("no open slots")
                continue
            raw = opens[index][position]
            if not (_ok(raw) and raw > 0):
                continue
            fill = raw * (1 + slip)
            deployed = deployed_notional(index)
            equity_est = cash + deployed
            sized = replace(
                rules,
                max_allocation_pct=max_alloc,
                max_portfolio_exposure=max_gross,
            )
            fraction = strategy.allocation_fraction(volatility, sized)
            room = max(0.0, sized.max_portfolio_exposure * equity_est - deployed)
            notional = min(equity_est * fraction, room, cash / (1 + cfg.fee_rate))
            if notional <= 0:
                skip("no remaining capital")
                continue
            fee = notional * cfg.fee_rate
            qty = notional / fill
            cash -= notional + fee
            result.fees_paid += fee
            lots.append(_Lot(
                symbol=symbol,
                idx=position,
                qty=qty,
                entry_price=fill,
                entry_cost=notional + fee,
                entry_time=timestamp,
                initial_stop=strategy.initial_stop_price(
                    fill, signal_atr, rules.atr_sl_mult
                ),
                active_stop=strategy.initial_stop_price(
                    fill, signal_atr, rules.atr_sl_mult
                ),
                highest_close=fill,
                bars_held=0,
                take_profit=strategy.take_profit_price(
                    fill, signal_atr, rules.take_profit_atr_mult
                ),
                entry_atr=signal_atr,
            ))
        pending_entries = []

        # 2. Stops were fixed on an earlier close, so this bar's low is fair game.
        for lot in list(lots):
            low = lows[index][lot.idx]
            if _ok(low) and lot.active_stop > 0 and low <= lot.active_stop:
                gap = opens[index][lot.idx]
                raw = gap if _ok(gap) and gap <= lot.active_stop else lot.active_stop
                reason = (
                    "trailing_stop"
                    if lot.active_stop > lot.initial_stop
                    else "initial_stop"
                )
                close_lot(lot, raw * (1 - slip), reason, timestamp)
                cooldown = rules.cooldown_days
                pending_exits.pop(lot.symbol, None)

        # 3. Take-profit scales out half the remaining lot against this bar's high.
        for lot in list(lots):
            if lot.tp_taken or lot.take_profit <= 0:
                continue
            high = highs[index][lot.idx]
            if not (_ok(high) and high >= lot.take_profit):
                continue
            gap = opens[index][lot.idx]
            raw = gap if _ok(gap) and gap >= lot.take_profit else lot.take_profit
            reduce_lot(lot, raw * (1 - slip), rules.take_profit_fraction, timestamp)

        # 4. Mark to market.
        equity = cash + sum(lot.qty * mark_lot(lot, index) for lot in lots)
        result.equity_curve.append({
            "timestamp": timestamp,
            "equity": equity,
            "symbol": ",".join(held_symbols()) or None,
        })
        result.bars += 1
        if not lots:
            result.cash_bars += 1

        # 5. Daily loss guard, then peak-heat / blow-off / 5-day shock.
        if previous_equity is not None and previous_equity > 0:
            drop = (previous_equity - equity) / previous_equity
            if drop >= cfg.daily_max_drawdown_pct:
                loss_guard_bars = 1
        previous_equity = equity
        heat = strategy.update_heat(
            heat, equity, in_market=bool(lots), rules=rules
        )

        # 6. Rank on this close; anything decided here fills at the next open.
        regime_snapshot = (
            strategy.AssetSnapshot(
                symbol=cfg.regime_symbol,
                close=closes[index][regime_position],
                trend_ema=_panel_value(panel.data, "trend_ema", index, regime_position),
                fast_ema=_panel_value(panel.data, "fast_ema", index, regime_position),
                breadth_ema=_panel_value(
                    panel.data, "breadth_ema", index, regime_position
                ),
                rsi=_panel_value(panel.data, "rsi", index, regime_position),
                roc_14=_panel_value(panel.data, "roc_14", index, regime_position),
                fast_ema_slope=_panel_value(
                    panel.data, "fast_ema_slope", index, regime_position
                ),
                fast_streak=_panel_value(
                    panel.data, "fast_streak", index, regime_position
                ),
            )
            if regime_position is not None
            else None
        )
        regime = strategy.evaluate_regime(
            regime_snapshot, rules, previous=previous_regime_snapshot
        )
        previous_regime_snapshot = regime_snapshot
        btc_5d = float("nan")
        if regime_position is not None and index >= rules.shock_lookback:
            btc_5d = strategy.lookback_return(
                float(closes[index][regime_position]),
                float(closes[index - rules.shock_lookback][regime_position]),
            )
        market_shock = strategy.update_market_shock(market_shock, btc_5d, rules)
        blowoff = strategy.is_blowoff(regime_snapshot, rules)
        equity_lock = strategy.update_equity_lock(
            equity_lock,
            equity,
            reclaim=strategy.btc_lock_reclaim(regime_snapshot, rules),
            rules=rules,
        )

        snapshots = [
            strategy.AssetSnapshot(
                symbol=symbol,
                close=closes[index][position],
                trend_ema=_panel_value(panel.data, "trend_ema", index, position),
                fast_ema=_panel_value(panel.data, "fast_ema", index, position),
                rsi=_panel_value(panel.data, "rsi", index, position),
                roc_14=_panel_value(panel.data, "roc_14", index, position),
                momentum=_panel_value(panel.data, "momentum", index, position),
                volatility=_panel_value(panel.data, "volatility", index, position),
                score=_panel_value(panel.data, "score", index, position),
                atr=atrs[index][position],
                dollar_volume=_panel_value(panel.data, "dollar_volume", index, position),
                bars_available=_panel_value(panel.data, "bars_available", index, position),
            )
            for symbol, position in positions.items()
        ]
        candidates = strategy.evaluate_candidates(snapshots, rules)

        if equity_lock.active:
            for lot in lots:
                pending_exits[lot.symbol] = "equity_lock"
            skip("equity lock")
        elif not regime.macro_on:
            for lot in lots:
                pending_exits[lot.symbol] = "regime_risk_off"
            skip("regime risk-off")
        elif market_shock:
            for lot in lots:
                pending_exits[lot.symbol] = "market_shock"
            skip("market shock")
        else:
            book_symbols = held_symbols()
            for lot in lots:
                reason = strategy.exit_reason(
                    lot.symbol,
                    candidates,
                    risk_on=True,
                    bars_held=lot.bars_held,
                    rules=rules,
                    held_symbols=book_symbols,
                    regime_symbol=cfg.regime_symbol,
                )
                if reason:
                    pending_exits[lot.symbol] = reason

            survivors = [lot for lot in lots if lot.symbol not in pending_exits]
            marks = {lot.symbol: mark_lot(lot, index) for lot in survivors}
            adjustment = strategy.book_adjustments(
                [
                    (
                        lot.symbol,
                        lot.qty * marks[lot.symbol],
                        lot.qty * marks[lot.symbol] - lot.entry_cost,
                    )
                    for lot in survivors
                ],
                equity=equity,
                heat_active=heat.active,
                defensive=False,
                rules=rules,
                regime_symbol=cfg.regime_symbol,
            )
            for symbol in adjustment.exit_symbols:
                pending_exits[symbol] = "heat"
            pending_reductions = {
                symbol: (frac, reason)
                for symbol, frac, reason in adjustment.reductions
                if symbol not in pending_exits
            }
            held_after_exits = [
                lot.symbol for lot in lots if lot.symbol not in pending_exits
            ]
            picks, skip_reason = strategy.select_new_entries(
                candidates,
                held_after_exits,
                rules,
                allow_new=regime.allow_new,
                blowoff=blowoff,
                market_shock=market_shock,
                heat_active=heat.active,
                cooldown=cooldown > 0,
                daily_loss_guard=loss_guard_bars > 0,
                regime_symbol=cfg.regime_symbol,
                equity_lock=False,
                max_open_slots=regime.max_open_slots,
                btc_5d_return=btc_5d,
                stop_pause=stop_pause > 0,
            )
            if skip_reason and len(held_after_exits) < rules.max_positions:
                skip(skip_reason)
            sized = strategy.entry_rules(
                rules,
                heat_active=heat.active,
                max_open_slots=regime.max_open_slots,
                drift_active=strategy.is_btc_drift(btc_5d, rules),
            )
            for pick in picks:
                pending_entries.append((
                    pick.symbol,
                    positions[pick.symbol],
                    pick.volatility,
                    pick.atr,
                    sized.max_allocation_pct,
                    sized.max_portfolio_exposure,
                ))
                if held_after_exits:
                    result.rotations += 1

        # 7. Ratchet each stop from this completed close.
        trail_mult = strategy.trail_multiple(rules, market_shock=market_shock)
        for lot in lots:
            mark = closes[index][lot.idx]
            close_atr = atrs[index][lot.idx]
            if _ok(mark) and _ok(close_atr):
                lot.active_stop, lot.highest_close = strategy.update_trailing_stop(
                    lot.active_stop,
                    lot.highest_close,
                    mark,
                    close_atr,
                    trail_mult,
                )
            lot.bars_held += 1

        if cooldown > 0:
            cooldown -= 1
        if loss_guard_bars > 0:
            loss_guard_bars -= 1

    if lots:
        last = len(dates) - 1
        for lot in list(lots):
            mark = closes[last][lot.idx]
            if _ok(mark):
                close_lot(lot, mark * (1 - slip), "end_of_test", dates[last])
        result.equity_curve[-1]["equity"] = cash
        result.equity_curve[-1]["symbol"] = None

    result.final_equity = cash
    return result
