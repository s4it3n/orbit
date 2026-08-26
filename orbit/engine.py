"""
Main loop for the Orbit daily momentum rotation bot.

Polls every LOOP_INTERVAL_SEC. Software stops check every poll; rankings and
rotations only run when a new completed daily bar appears.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
import time
from datetime import date, datetime, timezone

import ccxt
import pandas as pd

from . import config, data, execution, strategy, state as bot_state, notify as tg, universe
from . import exporter as orbit_exporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("orbit")

_notified_errors: set[str] = set()
_last_telegram_candle_ts: object | None = None
_guard: "DrawdownGuard | None" = None
_iteration_lock = threading.Lock()


class StateLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            bot_state.append_log(record.getMessage(), record.levelname)
        except Exception:
            pass


log.addHandler(StateLogHandler())


def get_guard() -> "DrawdownGuard":
    global _guard
    if _guard is None:
        _guard = DrawdownGuard()
    return _guard


def run_single_iteration() -> None:
    with _iteration_lock:
        run_iteration(get_guard())


class DrawdownGuard:
    """Tracks equity and persists the daily kill-switch."""

    def __init__(self) -> None:
        saved = bot_state.load_state().get("drawdown_state") or {}
        day_value = saved.get("day")
        self._day: date | None = date.fromisoformat(day_value) if day_value else None
        self._start_balance = float(saved.get("start_equity") or 0.0)
        self.trading_paused = bool(saved.get("paused", False))

    def _persist(self) -> None:
        bot_state.update_state(
            drawdown_state={
                "day": self._day.isoformat() if self._day else None,
                "start_equity": self._start_balance,
                "paused": self.trading_paused,
            },
            pause_reason="drawdown" if self.trading_paused else None,
        )

    def reset_if_new_day(self, equity: float) -> None:
        today = datetime.now(timezone.utc).date()
        if self._day != today:
            self._day = today
            self._start_balance = equity
            self.trading_paused = False
            self._persist()
            log.info("New trading day — start-of-day equity: %.2f USDT", equity)
            bot_state.append_operation("NEW_DAY", f"Start equity: {equity:.2f} USDT")

    def check(self, current_equity: float) -> bool:
        if self.trading_paused:
            return False
        if self._start_balance <= 0:
            return True
        drawdown = (self._start_balance - current_equity) / self._start_balance
        if drawdown >= config.DAILY_MAX_DRAWDOWN_PCT:
            log.critical(
                "DAILY DRAWDOWN LIMIT HIT: %.2f%% loss (limit %.2f%%). "
                "Trading PAUSED until next UTC day.",
                drawdown * 100,
                config.DAILY_MAX_DRAWDOWN_PCT * 100,
            )
            self.trading_paused = True
            self._persist()
            tg.notify_drawdown_kill(drawdown, current_equity)
            bot_state.append_operation(
                "DRAWDOWN",
                f"Daily loss {drawdown * 100:.2f}% — trading paused",
            )
            return False
        return True

    @property
    def start_balance(self) -> float:
        return self._start_balance


def _notify_error_once(key: str, title: str, detail: str) -> None:
    if key in _notified_errors:
        return
    _notified_errors.add(key)
    tg.notify_error(title, detail)
    bot_state.append_operation("ERROR", f"{title}: {detail}")


def _explain_auth_error(exc: ccxt.BaseError) -> None:
    message = str(exc)
    if "-1021" in message or "recvWindow" in message or "Timestamp" in message:
        log.error(
            "Binance rejected the request due to clock skew (code -1021). "
            "Enable NTP on the server or restart after config update."
        )
    if "451" in message or "restricted location" in message.lower():
        log.error(
            "Binance blocked this server's region (HTTP 451). "
            "Run the bot from an allowed location."
        )
    if "-2015" in message or "Invalid API-key" in message:
        log.error(
            "Binance rejected your API keys (code -2015). "
            "Use keys from https://testnet.binance.vision/"
        )


def fetch_usdt_balance() -> float:
    return execution.fetch_balances(
        config.exchange, config.REGIME_SYMBOL
    ).quote_free


def _flat_position() -> dict:
    return {
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
        "take_profit": None,
        "tp_taken": False,
        "entry_order_id": None,
        "protective_order_ids": [],
        "protection_status": None,
    }


def _is_long(position: dict | None) -> bool:
    return bool(
        position
        and position.get("status") == "long"
        and position.get("symbol")
    )


def _load_book(state_now: dict) -> list[dict]:
    raw = state_now.get("positions")
    if isinstance(raw, list) and raw:
        return [dict(item) for item in raw if _is_long(item)]
    position = state_now.get("position") or {}
    return [dict(position)] if _is_long(position) else []


def _held_symbols(book: list[dict]) -> list[str]:
    return [str(item["symbol"]) for item in book if _is_long(item)]


def _primary(book: list[dict]) -> dict:
    return dict(book[0]) if book else _flat_position()


def _persist_book(book: list[dict], **extra) -> None:
    symbols = _held_symbols(book)
    payload = {
        "positions": book,
        "position": _primary(book),
        "active_symbol": symbols[0] if symbols else None,
        "active_symbols": symbols,
    }
    payload.update(extra)
    bot_state.update_state(**payload)


def _fetch_live_frames() -> dict[str, pd.DataFrame]:
    """Pull recent daily candles for the universe + regime symbol."""
    symbols = universe.symbols_to_fetch(config.UNIVERSE)
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frames[symbol] = data.fetch_ohlcv(
                symbol=symbol,
                timeframe=config.TIMEFRAME,
                limit=config.CANDLE_LIMIT,
                public=True,
            )
        except Exception as exc:
            log.warning("Skipping %s: %s", symbol, exc)
    if config.REGIME_SYMBOL not in frames:
        raise ValueError(f"Could not fetch regime symbol {config.REGIME_SYMBOL}.")
    return frames


def _completed_row(frame: pd.DataFrame) -> pd.Series:
    completed = data.get_completed_candles(frame, count=1)
    return completed.iloc[-1]


def _previous_completed_row(frame: pd.DataFrame) -> pd.Series | None:
    try:
        completed = data.get_completed_candles(frame, count=2)
    except ValueError:
        return None
    if len(completed) < 2:
        return None
    return completed.iloc[-2]


def _mark_price(symbol: str, fallback: float) -> float:
    try:
        ticker = config.exchange.fetch_ticker(symbol)
        last = ticker.get("last")
        if last is not None:
            return float(last)
    except ccxt.BaseError:
        pass
    return float(fallback)


def _position_mark(position: dict, frames: dict[str, pd.DataFrame]) -> float | None:
    symbol = str(position.get("symbol") or "")
    fallback = float(position.get("entry_price") or 0.0)
    if symbol and symbol in frames:
        fallback = float(_completed_row(frames[symbol])["close"])
    if not symbol:
        return fallback or None
    return _mark_price(symbol, fallback)


def _total_equity(
    snapshot: execution.BalanceSnapshot,
    book: list[dict],
    frames: dict[str, pd.DataFrame] | None = None,
    mark: float | None = None,
) -> float:
    equity = snapshot.quote_total
    frames = frames or {}
    if not book and mark is not None:
        return equity
    for position in book:
        symbol = str(position.get("symbol") or "")
        if not symbol:
            continue
        price = _position_mark(position, frames)
        if price is None:
            continue
        try:
            held_snap = execution.fetch_balances(config.exchange, symbol)
            equity += held_snap.base_total * price
        except ccxt.BaseError:
            qty = float(position.get("quantity") or 0.0)
            equity += qty * price
    return equity


def _btc_lookback_return(frame: pd.DataFrame, lookback: int) -> float:
    try:
        completed = data.get_completed_candles(frame, count=lookback + 1)
    except ValueError:
        return float("nan")
    return strategy.lookback_return(
        float(completed.iloc[-1]["close"]),
        float(completed.iloc[0]["close"]),
    )


def _load_heat(state_now: dict) -> strategy.HeatState:
    saved = state_now.get("circuit") or {}
    return strategy.HeatState(
        peak_equity=float(saved.get("equity_peak") or 0.0),
        drawdown=float(saved.get("heat_drawdown_pct") or 0.0) / 100.0,
        active=bool(saved.get("heat_active")),
    )


def _load_equity_lock(state_now: dict) -> strategy.EquityLock:
    saved = state_now.get("circuit") or {}
    return strategy.EquityLock(
        all_time_peak=float(saved.get("all_time_peak") or 0.0),
        lock_peak=float(saved.get("lock_peak") or saved.get("all_time_peak") or 0.0),
        drawdown=float(saved.get("lock_drawdown_pct") or 0.0) / 100.0,
        active=bool(saved.get("equity_lock")),
    )


def _circuit_payload(
    heat: strategy.HeatState,
    *,
    market_shock: bool,
    blowoff: bool,
    btc_5d: float,
    equity_lock: strategy.EquityLock | None = None,
    stop_pause: int = 0,
) -> dict:
    lock = equity_lock or strategy.EquityLock()
    return {
        "stop_pause": int(stop_pause),
        "equity_peak": heat.peak_equity,
        "heat_active": heat.active,
        "heat_drawdown_pct": round(heat.drawdown * 100, 2),
        "market_shock": market_shock,
        "blowoff": blowoff,
        "btc_5d_return": None if not math.isfinite(btc_5d) else round(btc_5d * 100, 2),
        "equity_lock": lock.active,
        "all_time_peak": lock.all_time_peak,
        "lock_peak": lock.lock_peak,
        "lock_drawdown_pct": round(lock.drawdown * 100, 2),
    }


def _sync_state(
    guard: DrawdownGuard,
    *,
    snapshot: execution.BalanceSnapshot | None = None,
    price: float | None = None,
    position: dict | None = None,
    book: list[dict] | None = None,
    frames: dict[str, pd.DataFrame] | None = None,
    signal: str | None = None,
    candles: list | None = None,
    rankings: list | None = None,
    regime: dict | None = None,
    chart_symbol: str | None = None,
    market: dict | None = None,
    circuit: dict | None = None,
) -> None:
    if book is None:
        book = [position] if _is_long(position) else []
    position = _primary(book)
    equity = None
    display_equity = None
    paper_cap = float(config.ORBIT_PAPER_EQUITY)
    anchor: float | None = None
    if snapshot is not None:
        equity = _total_equity(snapshot, book, frames, price)
        # Map testnet balance into a $ORBIT_PAPER_EQUITY paper book via an anchor.
        # First sync (or missing anchor) sets the baseline so UI starts near $1k.
        from . import state as bot_state

        live = bot_state.load_state()
        raw_anchor = live.get("exchange_equity_anchor")
        if raw_anchor is None and equity is not None:
            anchor = float(equity)
        elif raw_anchor is not None:
            anchor = float(raw_anchor)
        if equity is not None and anchor is not None and anchor > 0:
            display_equity = max(0.0, paper_cap + (float(equity) - anchor))
        elif equity is not None:
            display_equity = min(float(equity), paper_cap)
    drawdown = 0.0
    if guard.start_balance > 0 and equity is not None:
        drawdown = max(0.0, (guard.start_balance - equity) / guard.start_balance)
    symbols = _held_symbols(book)
    fields: dict = {
        "balance_usdt": snapshot.quote_free if snapshot else None,
        "equity_usdt": display_equity,
        "paper_equity_cap": paper_cap,
        "exchange_equity_usdt": equity,
        "exchange_equity_anchor": float(anchor) if anchor is not None else None,
        "base_balance": snapshot.base_total if snapshot else None,
        "start_of_day_balance": guard.start_balance or equity,
        "daily_drawdown_pct": round(drawdown * 100, 2),
        "trading_paused": guard.trading_paused or not config.BOT_ENABLED,
        "pause_reason": (
            "drawdown" if guard.trading_paused
            else "manual" if not config.BOT_ENABLED
            else None
        ),
        "last_signal": signal,
        "active_symbol": symbols[0] if symbols else None,
        "active_symbols": symbols,
        "positions": book,
        "position": position,
    }
    if market is not None:
        fields["market"] = market
    if candles is not None:
        fields["candles"] = candles
    if rankings is not None:
        fields["rankings"] = rankings
    if regime is not None:
        fields["regime"] = regime
    if chart_symbol is not None:
        fields["chart_symbol"] = chart_symbol
    if circuit is not None:
        fields["circuit"] = circuit
    bot_state.update_state(**fields)


def _exit_long(
    position: dict,
    price: float,
    reason: str,
    candle_ts: object,
    book: list[dict] | None = None,
) -> list[dict]:
    symbol = str(position.get("symbol") or "")
    remaining = [
        item for item in (book or [])
        if str(item.get("symbol")) != symbol
    ]
    cooldown = config.COOLDOWN_DAYS if reason in {"initial_stop", "trailing_stop"} else None
    extra = {"cooldown_days_remaining": cooldown} if cooldown is not None else {}
    if not symbol:
        _persist_book(remaining, **extra)
        return remaining
    execution.cancel_open_orders(config.exchange, symbol)
    snapshot = execution.fetch_balances(config.exchange, symbol)
    desired = min(float(position.get("quantity") or 0.0), snapshot.base_free)
    quantity = execution.normalize_quantity(
        config.exchange, symbol, desired, price
    )
    if quantity <= 0:
        log.warning("No sellable base balance remains for %s; dropping lot.", symbol)
        _persist_book(remaining, **extra)
        return remaining
    fill = execution.place_market_order(
        config.exchange,
        symbol,
        "sell",
        quantity,
        price,
        execution.client_order_id(symbol, candle_ts, f"exit-{reason}"),
    )
    entry = float(position.get("entry_price") or fill.average_price)
    pnl = (fill.average_price - entry) * fill.quantity - fill.fee
    _persist_book(remaining, **extra)
    bot_state.append_operation(
        "EXIT",
        f"SELL {symbol} {fill.quantity:.8f} @ {data.round_price(fill.average_price)} ({reason})",
        {"pnl_usdt": pnl, "order_id": fill.order_id, "symbol": symbol},
    )
    tg.notify_exit(symbol, fill.quantity, fill.average_price, pnl, reason)
    log.info(
        "Long closed (%s): %s %.8f @ %.8f, PnL≈%.2f",
        reason, symbol, fill.quantity, fill.average_price, pnl,
    )
    return remaining


def _reduce_long(
    position: dict,
    price: float,
    fraction: float,
    candle_ts: object,
    book: list[dict],
    reason: str = "take_profit",
) -> list[dict]:
    symbol = str(position.get("symbol") or "")
    if not symbol:
        return book
    if reason == "take_profit" and position.get("tp_taken"):
        return book
    execution.cancel_open_orders(config.exchange, symbol)
    snapshot = execution.fetch_balances(config.exchange, symbol)
    desired = min(
        float(position.get("quantity") or 0.0) * fraction,
        snapshot.base_free,
    )
    quantity = execution.normalize_quantity(
        config.exchange, symbol, desired, price
    )
    if quantity <= 0:
        log.warning("Take-profit quantity for %s is below exchange limits.", symbol)
        return book
    fill = execution.place_market_order(
        config.exchange,
        symbol,
        "sell",
        quantity,
        price,
        execution.client_order_id(symbol, candle_ts, reason.replace("_", "-")[:24]),
    )
    entry = float(position.get("entry_price") or fill.average_price)
    pnl = (fill.average_price - entry) * fill.quantity - fill.fee
    position["quantity"] = max(
        0.0, float(position.get("quantity") or 0.0) - fill.quantity
    )
    if reason == "take_profit":
        position["tp_taken"] = True
    remaining_qty = float(position["quantity"])
    if remaining_qty > 0:
        try:
            ids = execution.place_catastrophic_stop(
                config.exchange,
                symbol,
                remaining_qty,
                float(position.get("trailing_stop") or position.get("initial_stop") or 0.0),
            )
            if ids:
                position["protective_order_ids"] = ids
                position["protection_status"] = "exchange_stop"
        except ccxt.BaseError as exc:
            log.warning("Could not replace exchange stop after take-profit: %s", exc)
        updated = [
            position if str(item.get("symbol")) == symbol else item
            for item in book
        ]
    else:
        updated = [item for item in book if str(item.get("symbol")) != symbol]
    _persist_book(updated)
    bot_state.append_operation(
        "TAKE_PROFIT",
        f"SELL {symbol} {fill.quantity:.8f} @ {data.round_price(fill.average_price)} ({reason})",
        {"pnl_usdt": pnl, "order_id": fill.order_id, "symbol": symbol},
    )
    tg.notify_exit(symbol, fill.quantity, fill.average_price, pnl, reason)
    log.info(
        "Take-profit filled: %s %.8f @ %.8f, PnL≈%.2f",
        symbol, fill.quantity, fill.average_price, pnl,
    )
    return updated


def _enter_long(
    candidate: strategy.Candidate,
    snapshot: execution.BalanceSnapshot,
    candle_ts: object,
    book: list[dict],
    frames: dict[str, pd.DataFrame],
    rules: strategy.RotationRules | None = None,
) -> list[dict]:
    rules = rules or strategy.current_rules()
    if any(str(item.get("symbol")) == candidate.symbol for item in book):
        return book
    if len(book) >= rules.max_positions:
        log.info("All %d slots are filled — skipping %s.", rules.max_positions, candidate.symbol)
        return book
    raw_equity = _total_equity(snapshot, book, frames)
    # Size off paper capital so testnet balances >> $1k do not inflate live sizing.
    equity = min(raw_equity, float(config.ORBIT_PAPER_EQUITY))
    deployed = 0.0
    for item in book:
        price = _position_mark(item, frames)
        if price is not None:
            deployed += float(item.get("quantity") or 0.0) * price
    fraction = strategy.allocation_fraction(candidate.volatility, rules)
    room = max(0.0, rules.max_portfolio_exposure * equity - deployed)
    notional = min(equity * fraction, room, snapshot.quote_free)
    if notional <= 0 or candidate.close <= 0:
        log.warning("No remaining capital for a new slot.")
        return book
    quantity = execution.normalize_quantity(
        config.exchange,
        candidate.symbol,
        notional / candidate.close,
        candidate.close,
        available_quote=snapshot.quote_free,
    )
    if quantity <= 0:
        log.warning("Entry quantity is below exchange limits or available cash.")
        return book
    fill = execution.place_market_order(
        config.exchange,
        candidate.symbol,
        "buy",
        quantity,
        candidate.close,
        execution.client_order_id(candidate.symbol, candle_ts, "entry"),
    )
    if fill.quantity <= 0:
        raise ccxt.InvalidOrder("Entry order did not report a filled quantity.")
    initial_stop = strategy.initial_stop_price(
        fill.average_price, candidate.atr, rules.atr_sl_mult
    )
    position = {
        "status": "long",
        "symbol": candidate.symbol,
        "quantity": fill.quantity,
        "entry_price": fill.average_price,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "entry_bar_ts": str(candle_ts),
        "bars_held": 0,
        "stop_loss": initial_stop,
        "initial_stop": initial_stop,
        "trailing_stop": initial_stop,
        "highest_close": fill.average_price,
        "take_profit": strategy.take_profit_price(
            fill.average_price, candidate.atr, rules.take_profit_atr_mult
        ),
        "entry_atr": candidate.atr,
        "tp_taken": False,
        "entry_order_id": fill.order_id,
        "protective_order_ids": [],
        "protection_status": "software",
    }
    try:
        ids = execution.place_catastrophic_stop(
            config.exchange,
            candidate.symbol,
            fill.quantity,
            initial_stop,
        )
        if ids:
            position["protective_order_ids"] = ids
            position["protection_status"] = "exchange_stop"
    except ccxt.BaseError as exc:
        log.warning("Exchange stop unavailable; software exit remains active: %s", exc)
    book = book + [position]
    _persist_book(book)
    bot_state.append_operation(
        "ENTRY",
        f"BUY {candidate.symbol} {fill.quantity:.8f} @ "
        f"{data.round_price(fill.average_price)}",
        {
            "initial_stop": initial_stop,
            "take_profit": position["take_profit"],
            "order_id": fill.order_id,
            "symbol": candidate.symbol,
            "score": candidate.score,
        },
    )
    tg.notify_entry(position)
    log.info(
        "Long opened: %s %.8f @ %.8f, initial stop %.8f, TP %.8f (%s)",
        candidate.symbol, fill.quantity, fill.average_price, initial_stop,
        position["take_profit"], position["protection_status"],
    )
    return book


def run_iteration(guard: DrawdownGuard) -> None:
    config.reload_settings()
    if not config.BOT_ENABLED:
        log.info("Orbit paused via dashboard — skipping iteration.")
        _sync_state(guard)
        return

    try:
        frames = _fetch_live_frames()
        regime_frame = frames[config.REGIME_SYMBOL]
        regime_latest = _completed_row(regime_frame)
        candle_ts = str(regime_latest["timestamp"])
        quote_snapshot = execution.fetch_balances(
            config.exchange, config.REGIME_SYMBOL
        )
    except (ccxt.BaseError, ValueError) as exc:
        log.error("Failed to fetch account or market data: %s", exc)
        if isinstance(exc, ccxt.BaseError):
            _explain_auth_error(exc)
        _notify_error_once("iteration_fetch", "Failed to fetch bot data", str(exc))
        _sync_state(guard)
        return

    state_now = bot_state.load_state()
    book = _load_book(state_now)
    stop_pause = int((state_now.get("circuit") or {}).get("stop_pause") or 0)
    snapshot = quote_snapshot
    reconciled: list[dict] = []
    for position in book:
        symbol = str(position["symbol"])
        if symbol not in frames:
            reconciled.append(position)
            continue
        try:
            held_snap = execution.fetch_balances(config.exchange, symbol)
        except ccxt.BaseError:
            reconciled.append(position)
            continue
        if held_snap.base_total < float(position.get("quantity") or 0) * 0.25:
            log.info("%s no longer exists on exchange; dropping lot.", symbol)
            bot_state.append_operation("EXIT", f"{symbol} closed on exchange (reconciled)")
            continue
        reconciled.append(position)
    if len(reconciled) != len(book):
        book = reconciled
        _persist_book(book)

    equity = _total_equity(snapshot, book, frames)
    guard.reset_if_new_day(equity)
    held = _held_symbols(book)
    chart_symbol = held[0] if held else config.REGIME_SYMBOL
    chart_frame = frames.get(chart_symbol, regime_frame)
    chart_candles = data.candles_for_chart(chart_frame.iloc[:-1])
    primary_mark = (
        _position_mark(book[0], frames) if book
        else float(regime_latest["close"])
    )

    if not guard.check(equity):
        if config.FLATTEN_ON_DRAWDOWN:
            for position in list(book):
                price = _position_mark(position, frames) or primary_mark
                book = _exit_long(
                    position, price, "drawdown", regime_latest["timestamp"], book
                )
        _sync_state(
            guard,
            snapshot=snapshot,
            price=primary_mark,
            book=book,
            frames=frames,
            candles=chart_candles,
            chart_symbol=chart_symbol,
        )
        return

    rules = strategy.current_rules()

    # Software stops and take-profits every poll.
    for position in list(book):
        mark = _position_mark(position, frames)
        if mark is None:
            continue
        active_stop = float(
            position.get("trailing_stop")
            or position.get("stop_loss")
            or position.get("initial_stop")
            or 0.0
        )
        if active_stop > 0 and mark <= active_stop:
            reason = (
                "initial_stop"
                if active_stop <= float(position.get("initial_stop") or active_stop)
                else "trailing_stop"
            )
            book = _exit_long(position, mark, reason, regime_latest["timestamp"], book)
            pause = strategy.start_stop_pause(reason, rules)
            if pause > stop_pause:
                stop_pause = pause
            continue
        take_profit = float(position.get("take_profit") or 0.0)
        if take_profit > 0 and not position.get("tp_taken") and mark >= take_profit:
            book = _reduce_long(
                position, mark, config.TAKE_PROFIT_FRACTION,
                regime_latest["timestamp"], book,
            )

    snapshot = execution.fetch_balances(config.exchange, config.REGIME_SYMBOL)
    equity = _total_equity(snapshot, book, frames)
    held = _held_symbols(book)
    chart_symbol = held[0] if held else config.REGIME_SYMBOL
    primary_mark = (
        _position_mark(book[0], frames) if book
        else float(regime_latest["close"])
    )

    snapshots = []
    for symbol, frame in frames.items():
        if symbol not in config.UNIVERSE:
            continue
        try:
            snapshots.append(strategy.snapshot_from_series(symbol, _completed_row(frame)))
        except ValueError:
            continue
    candidates = strategy.evaluate_candidates(snapshots, rules)
    rankings = strategy.rankings_payload(candidates, held)
    regime_snap = strategy.snapshot_from_series(config.REGIME_SYMBOL, regime_latest)
    previous_regime = None
    prev_row = _previous_completed_row(regime_frame)
    if prev_row is not None:
        previous_regime = strategy.snapshot_from_series(config.REGIME_SYMBOL, prev_row)
    regime = strategy.evaluate_regime(regime_snap, rules, previous=previous_regime)
    btc_5d = _btc_lookback_return(regime_frame, rules.shock_lookback)
    saved_circuit = state_now.get("circuit") or {}
    heat = strategy.update_heat(
        _load_heat(state_now),
        equity,
        in_market=bool(book),
        rules=rules,
    )
    market_shock = strategy.update_market_shock(
        bool(saved_circuit.get("market_shock")),
        btc_5d,
        rules,
    )
    blowoff = strategy.is_blowoff(regime_snap, rules)
    equity_lock = strategy.update_equity_lock(
        _load_equity_lock(state_now),
        equity,
        reclaim=strategy.btc_lock_reclaim(regime_snap, rules),
        rules=rules,
    )
    circuit = _circuit_payload(
        heat,
        market_shock=market_shock,
        blowoff=blowoff,
        btc_5d=btc_5d,
        equity_lock=equity_lock,
        stop_pause=stop_pause,
    )
    regime_info = {
        "risk_on": regime.macro_on,
        "allow_new": (
            regime.allow_new and not market_shock and not equity_lock.active
        ),
        "reason": "equity-lock" if equity_lock.active else regime.reason,
        "symbol": config.REGIME_SYMBOL,
        "close": float(regime_latest["close"]),
        "trend_ema": float(regime_latest["trend_ema"])
        if pd.notna(regime_latest.get("trend_ema")) else None,
        "fast_ema": float(regime_latest["fast_ema"])
        if pd.notna(regime_latest.get("fast_ema")) else None,
        "rsi": float(regime_latest["rsi"])
        if pd.notna(regime_latest.get("rsi")) else None,
        "candle_time": candle_ts,
        "heat_active": heat.active,
        "market_shock": market_shock,
        "blowoff": blowoff,
        "defensive": regime.defensive,
        "max_open_slots": regime.max_open_slots,
        "equity_lock": equity_lock.active,
        "lock_drawdown_pct": circuit["lock_drawdown_pct"],
        "btc_5d_return": circuit["btc_5d_return"],
        "heat_drawdown_pct": circuit["heat_drawdown_pct"],
    }
    targets = strategy.select_targets(candidates, rules) if regime.allow_new else []
    market = {
        "candle_time": candle_ts,
        "close": primary_mark,
        "chart_symbol": chart_symbol,
        "held_symbol": ",".join(held) if held else None,
        "top_symbol": targets[0].symbol if targets else None,
        "trend_ema": (
            float(_completed_row(frames[chart_symbol])["trend_ema"])
            if chart_symbol in frames
            and pd.notna(_completed_row(frames[chart_symbol]).get("trend_ema"))
            else None
        ),
    }

    if state_now.get("last_processed_candle_ts") == candle_ts:
        _sync_state(
            guard,
            snapshot=snapshot,
            price=primary_mark,
            book=book,
            frames=frames,
            candles=chart_candles,
            rankings=rankings,
            regime=regime_info,
            chart_symbol=chart_symbol,
            market=market,
            circuit=circuit,
        )
        return

    cooldown = max(0, int(state_now.get("cooldown_days_remaining") or 0) - 1)
    stop_pause = strategy.decay_stop_pause(stop_pause)
    bot_state.update_state(
        last_processed_candle_ts=candle_ts,
        cooldown_days_remaining=cooldown,
    )

    trail_mult = strategy.trail_multiple(rules, market_shock=market_shock)
    for position in book:
        symbol = str(position["symbol"])
        if symbol not in frames:
            continue
        held_row = _completed_row(frames[symbol])
        old_stop = float(
            position.get("trailing_stop")
            or position.get("initial_stop")
            or position.get("stop_loss")
            or 0.0
        )
        new_stop, highest = strategy.update_trailing_stop(
            old_stop,
            float(position.get("highest_close") or position["entry_price"]),
            float(held_row["close"]),
            float(held_row["atr"]),
            trail_mult,
        )
        position["trailing_stop"] = new_stop
        position["stop_loss"] = new_stop
        position["highest_close"] = highest
        position["bars_held"] = int(position.get("bars_held") or 0) + 1
        if new_stop > old_stop:
            log.info("Trailing stop raised on %s from %.8f to %.8f", symbol, old_stop, new_stop)
    if book:
        _persist_book(book)

    if equity_lock.active:
        log.info(
            "Equity lock on — session DD %.2f%% from peak; flattened to cash.",
            equity_lock.drawdown * 100,
        )
    if heat.active and not equity_lock.active:
        log.info(
            "Risk mitigation on — peak DD %.2f%%; keeping best lot at half size.",
            heat.drawdown * 100,
        )
    if not regime.allow_new and regime.macro_on and not equity_lock.active:
        log.info("Fast regime off — blocking new entries.")
    if market_shock:
        log.info(
            "Market shock on — BTC 5d %+0.2f%%; flattening to cash, no new buys.",
            (btc_5d * 100) if math.isfinite(btc_5d) else float("nan"),
        )
    if blowoff:
        log.info("Blow-off on — blocking new altcoin entries.")

    global _last_telegram_candle_ts
    if regime_latest["timestamp"] != _last_telegram_candle_ts:
        _last_telegram_candle_ts = regime_latest["timestamp"]
        tg.notify_daily(
            candle_time=str(candle_ts),
            risk_on=regime.macro_on,
            held=held[0] if held else None,
            top=targets[0].symbol if targets else None,
            equity=equity,
        )

    signal = None
    try:
        if equity_lock.active:
            for position in list(book):
                price = _position_mark(position, frames) or primary_mark
                book = _exit_long(position, price, "equity_lock", candle_ts, book)
                signal = "EQUITY_LOCK"
            snapshot = execution.fetch_balances(config.exchange, config.REGIME_SYMBOL)
        elif not regime.macro_on:
            for position in list(book):
                price = _position_mark(position, frames) or primary_mark
                book = _exit_long(position, price, "regime_risk_off", candle_ts, book)
                signal = "REGIME_RISK_OFF"
            snapshot = execution.fetch_balances(config.exchange, config.REGIME_SYMBOL)
        elif market_shock:
            for position in list(book):
                price = _position_mark(position, frames) or primary_mark
                book = _exit_long(position, price, "market_shock", candle_ts, book)
                signal = "MARKET_SHOCK"
            snapshot = execution.fetch_balances(config.exchange, config.REGIME_SYMBOL)
        else:
            book_symbols = _held_symbols(book)
            for position in list(book):
                leave = strategy.exit_reason(
                    str(position["symbol"]),
                    candidates,
                    risk_on=True,
                    bars_held=int(position.get("bars_held") or 0),
                    rules=rules,
                    held_symbols=book_symbols,
                    regime_symbol=config.REGIME_SYMBOL,
                )
                if not leave:
                    continue
                signal = leave.upper()
                price = _position_mark(position, frames) or primary_mark
                book = _exit_long(position, price, leave, candle_ts, book)
            snapshot = execution.fetch_balances(config.exchange, config.REGIME_SYMBOL)
            equity = _total_equity(snapshot, book, frames)
            survivors = []
            for position in book:
                mark = _position_mark(position, frames)
                if mark is None:
                    mark = float(position.get("entry_price") or 0.0)
                qty = float(position.get("quantity") or 0.0)
                entry = float(position.get("entry_price") or mark)
                survivors.append((
                    str(position["symbol"]),
                    qty * mark,
                    qty * (mark - entry),
                ))
            adjustment = strategy.book_adjustments(
                survivors,
                equity=equity,
                heat_active=heat.active,
                defensive=False,
                rules=rules,
                regime_symbol=config.REGIME_SYMBOL,
            )
            for symbol in adjustment.exit_symbols:
                position = next(
                    (item for item in book if str(item.get("symbol")) == symbol),
                    None,
                )
                if position is None:
                    continue
                price = _position_mark(position, frames) or primary_mark
                book = _exit_long(position, price, "heat", candle_ts, book)
                signal = "HEAT"
            for symbol, frac, reason in adjustment.reductions:
                position = next(
                    (item for item in book if str(item.get("symbol")) == symbol),
                    None,
                )
                if position is None:
                    continue
                price = _position_mark(position, frames) or primary_mark
                book = _reduce_long(
                    position, price, frac, candle_ts, book, reason
                )
            snapshot = execution.fetch_balances(config.exchange, config.REGIME_SYMBOL)
            held = _held_symbols(book)
            picks, skip_reason = strategy.select_new_entries(
                candidates,
                held,
                rules,
                allow_new=regime.allow_new,
                blowoff=blowoff,
                market_shock=market_shock,
                heat_active=heat.active,
                cooldown=cooldown > 0,
                daily_loss_guard=False,
                regime_symbol=config.REGIME_SYMBOL,
                equity_lock=False,
                max_open_slots=regime.max_open_slots,
                btc_5d_return=btc_5d,
                stop_pause=stop_pause > 0,
            )
            if skip_reason:
                log.info("Entry skipped — %s.", skip_reason)
            sized = strategy.entry_rules(
                rules,
                heat_active=heat.active,
                max_open_slots=regime.max_open_slots,
                drift_active=strategy.is_btc_drift(btc_5d, rules),
            )
            for pick in picks:
                signal = "ROTATE" if held else "ENTER"
                bot_state.append_operation(
                    "SIGNAL",
                    f"Target {pick.symbol} (rank {pick.rank}, score {pick.score:.3f})",
                    {"symbol": pick.symbol, "score": pick.score},
                )
                book = _enter_long(pick, snapshot, candle_ts, book, frames, sized)
                snapshot = execution.fetch_balances(
                    config.exchange, config.REGIME_SYMBOL
                )
                held = _held_symbols(book)
    except (ccxt.BaseError, ValueError) as exc:
        log.error("Order lifecycle failed: %s", exc)
        tg.notify_order_error(signal or "ROTATION", str(exc))
        bot_state.append_operation("ERROR", f"Order lifecycle failed: {exc}")

    held = _held_symbols(book)
    chart_symbol = held[0] if held else config.REGIME_SYMBOL
    chart_frame = frames.get(chart_symbol, regime_frame)
    chart_candles = data.candles_for_chart(chart_frame.iloc[:-1])
    rankings = strategy.rankings_payload(candidates, held)
    heat = strategy.update_heat(
        heat,
        _total_equity(snapshot, book, frames),
        in_market=bool(book),
        rules=rules,
    )
    equity_lock = strategy.update_equity_lock(
        equity_lock,
        _total_equity(snapshot, book, frames),
        reclaim=strategy.btc_lock_reclaim(regime_snap, rules),
        rules=rules,
    )
    circuit = _circuit_payload(
        heat,
        market_shock=market_shock,
        blowoff=blowoff,
        btc_5d=btc_5d,
        equity_lock=equity_lock,
        stop_pause=stop_pause,
    )
    _sync_state(
        guard,
        snapshot=snapshot,
        price=_position_mark(book[0], frames) if book else float(regime_latest["close"]),
        book=book,
        frames=frames,
        signal=signal,
        candles=chart_candles,
        rankings=rankings,
        regime=regime_info,
        chart_symbol=chart_symbol,
        market=market,
        circuit=circuit,
    )
    try:
        orbit_exporter.export_state()
    except Exception:
        log.exception("Failed to export orbit_state.json")


def run_bot_loop(stop_event: threading.Event | None = None) -> None:
    log.info("=" * 60)
    log.info("Orbit starting (Binance SANDBOX mode)")
    config.reload_settings()
    log.info(
        "Universe=%d coins  Timeframe=%s  Max daily DD=%.1f%%  Enabled=%s",
        len(config.UNIVERSE),
        config.TIMEFRAME,
        config.DAILY_MAX_DRAWDOWN_PCT * 100,
        config.BOT_ENABLED,
    )
    log.info("=" * 60)

    bot_state.set_bot_running(True)
    bot_state.append_operation("START", "Orbit started")
    try:
        orbit_exporter.export_state()
    except Exception:
        log.exception("Failed to export orbit_state.json on start")

    if not config.BINANCE_API_KEY or not config.BINANCE_SECRET_KEY:
        log.warning("BINANCE_API_KEY / BINANCE_SECRET_KEY not set.")

    guard = get_guard()

    if tg.is_configured():
        log.info("Telegram alerts enabled (important events only).")
        startup_balance: float | None = None
        try:
            startup_balance = fetch_usdt_balance()
        except ccxt.BaseError:
            pass
        tg.notify_startup(startup_balance)

    try:
        while stop_event is None or not stop_event.is_set():
            try:
                with _iteration_lock:
                    run_iteration(guard)
            except Exception as exc:
                log.exception("Unexpected error in Orbit loop")
                tg.notify_error("error", str(exc))
                bot_state.append_operation("ERROR", str(exc))

            interval = config.LOOP_INTERVAL_SEC
            log.info("Sleeping %d seconds…", interval)
            for _ in range(interval):
                if stop_event is not None and stop_event.is_set():
                    break
                time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutdown requested — exiting.")
        bot_state.append_operation("STOP", "Orbit stopped")
    finally:
        bot_state.set_bot_running(False)
        log.info("Orbit loop exited.")


def main() -> None:
    run_bot_loop()


if __name__ == "__main__":
    main()
