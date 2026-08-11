"""
Main entry point for the EMA paper-trading bot.

Runs a polling loop every 60 seconds, checks for EMA crossover signals,
and places sandbox orders with ATR-based risk management.  Includes a
daily drawdown kill-switch that halts trading when losses exceed 3 %.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timezone

import ccxt

import config
import data
import strategy
import telegram_notify as tg

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ema-bot")

LOOP_INTERVAL_SEC: int = 60

# Avoid spamming Telegram with the same error every loop iteration.
_notified_errors: set[str] = set()

# Track the last candle we already reported to Telegram.
_last_telegram_candle_ts: object | None = None


class DrawdownGuard:
    """Tracks intraday balance and enforces the daily max drawdown limit."""

    def __init__(self) -> None:
        self._day: date | None = None
        self._start_balance: float = 0.0
        self.trading_paused: bool = False

    def reset_if_new_day(self, balance: float) -> None:
        today = datetime.now(timezone.utc).date()
        if self._day != today:
            self._day = today
            self._start_balance = balance
            self.trading_paused = False
            log.info(
                "New trading day — start-of-day balance: %.2f USDT", balance
            )
            tg.notify_new_day(balance)

    def check(self, current_balance: float) -> bool:
        """
        Return ``True`` if trading is allowed, ``False`` if the kill-switch
        has tripped.
        """
        if self._start_balance <= 0:
            return True

        drawdown = (self._start_balance - current_balance) / self._start_balance

        if drawdown >= config.DAILY_MAX_DRAWDOWN_PCT:
            if not self.trading_paused:
                log.critical(
                    "DAILY DRAWDOWN LIMIT HIT: %.2f%% loss (limit %.2f%%). "
                    "Trading PAUSED until next UTC day.",
                    drawdown * 100,
                    config.DAILY_MAX_DRAWDOWN_PCT * 100,
                )
                self.trading_paused = True
                tg.notify_drawdown_kill(drawdown, current_balance)
            return False

        return True


def _notify_if_new_candle(
    latest,
    balance: float,
    signal: strategy.Signal,
) -> None:
    """Telegram update when a new completed candle appears (~once per hour)."""
    global _last_telegram_candle_ts

    candle_ts = latest["timestamp"]
    if candle_ts == _last_telegram_candle_ts:
        return

    _last_telegram_candle_ts = candle_ts

    if signal is not None:
        # Crossover messages are sent separately with trade details.
        return

    tg.notify_hourly_status(
        candle_time=str(candle_ts),
        close=float(latest["close"]),
        ema_fast=float(latest["ema_fast"]),
        ema_slow=float(latest["ema_slow"]),
        atr=float(latest["atr"]),
        balance=balance,
    )


def _notify_error_once(key: str, title: str, detail: str) -> None:
    """Send a Telegram error alert at most once per key per session."""
    if key in _notified_errors:
        return
    _notified_errors.add(key)
    tg.notify_error(title, detail)


def _explain_auth_error(exc: ccxt.BaseError) -> None:
    """Log actionable guidance for common Binance auth failures."""
    message = str(exc)
    if "-2015" in message or "Invalid API-key" in message:
        log.error(
            "Binance rejected your API keys (code -2015). Common causes:\n"
            "  1. Keys were created on binance.com — they will NOT work here.\n"
            "     Create new keys at https://testnet.binance.vision/ (Spot Testnet).\n"
            "  2. Keys were copied incorrectly — check .env for extra spaces/quotes.\n"
            "  3. IP restrictions on the key block this machine.\n"
            "  4. Key lacks 'Enable Reading' / spot trading permissions on testnet."
        )


def fetch_usdt_balance() -> float:
    """Return free USDT balance from the exchange account."""
    balance = config.exchange.fetch_balance()
    return float(balance.get("USDT", {}).get("free", 0.0))


def execute_paper_order(plan: strategy.TradePlan) -> None:
    """Place a market order on the Binance sandbox account."""
    order_side = "buy" if plan.side == "BUY" else "sell"

    log.info(
        "Executing %s order [SANDBOX] — qty=%.8f  entry≈%.2f  "
        "SL=%.2f  TP=%.2f  (ATR=%.2f)",
        plan.side,
        plan.quantity,
        plan.entry_price,
        plan.stop_loss,
        plan.take_profit,
        plan.atr,
    )

    order = config.exchange.create_market_order(
        config.TRADING_SYMBOL,
        order_side,
        plan.quantity,
    )
    log.info("Order filled: id=%s  status=%s", order.get("id"), order.get("status"))
    tg.notify_order(plan, str(order.get("id", "?")), str(order.get("status", "?")))


def run_iteration(guard: DrawdownGuard) -> None:
    """Single loop iteration: fetch → signal → (maybe) trade."""
    # --- Balance & drawdown check -----------------------------------------
    log.info("Fetching account balance…")
    try:
        balance = fetch_usdt_balance()
    except ccxt.BaseError as exc:
        log.error("Failed to fetch balance: %s", exc)
        _explain_auth_error(exc)
        _notify_error_once("balance_fetch", "Failed to fetch balance", str(exc))
        return

    log.info("Current USDT balance: %.2f", balance)
    guard.reset_if_new_day(balance)

    if not guard.check(balance):
        log.warning("Trading paused by drawdown kill-switch — skipping signals.")
        return

    # --- Market data -------------------------------------------------------
    log.info(
        "Fetching %d × %s candles for %s…",
        config.CANDLE_LIMIT,
        config.TIMEFRAME,
        config.TRADING_SYMBOL,
    )
    try:
        df = data.fetch_ohlcv()
    except ccxt.BaseError as exc:
        log.error("Failed to fetch OHLCV data: %s", exc)
        _notify_error_once("ohlcv_fetch", "Failed to fetch market data", str(exc))
        return

    try:
        completed = data.get_completed_candles(df, count=2)
    except ValueError as exc:
        log.warning("Insufficient candle data: %s", exc)
        return

    latest = completed.iloc[-1]
    log.info(
        "Latest completed candle: %s  close=%.2f  EMA%d=%.2f  EMA%d=%.2f  ATR=%.2f",
        latest["timestamp"],
        latest["close"],
        config.EMA_FAST,
        latest["ema_fast"],
        config.EMA_SLOW,
        latest["ema_slow"],
        latest["atr"],
    )

    # --- Signal evaluation -------------------------------------------------
    log.info("Checking EMA crossover signals…")
    signal = strategy.evaluate_signal(completed)

    _notify_if_new_candle(latest, balance, signal)

    if signal is None:
        log.info("No signal — waiting for next candle.")
        return

    log.info("Signal detected: %s", signal)
    tg.notify_signal(
        signal,
        float(latest["close"]),
        float(latest["ema_fast"]),
        float(latest["ema_slow"]),
        float(latest["atr"]),
    )

    # --- Trade execution ---------------------------------------------------
    plan = strategy.build_trade_plan(signal, balance, latest)

    if plan.quantity <= 0:
        log.warning("Calculated quantity is zero — skipping order.")
        return

    try:
        execute_paper_order(plan)
    except ccxt.InsufficientFunds as exc:
        log.error("Insufficient funds for order: %s", exc)
        tg.notify_order_error(signal, str(exc))
    except ccxt.InvalidOrder as exc:
        log.error("Invalid order rejected by exchange: %s", exc)
        tg.notify_order_error(signal, str(exc))
    except ccxt.BaseError as exc:
        log.error("Exchange error while placing order: %s", exc)
        tg.notify_order_error(signal, str(exc))


def main() -> None:
    log.info("=" * 60)
    log.info("EMA Paper-Trading Bot starting (Binance SANDBOX mode)")
    log.info(
        "Symbol=%s  Timeframe=%s  Risk/trade=%.0f%%  Max daily DD=%.0f%%",
        config.TRADING_SYMBOL,
        config.TIMEFRAME,
        config.RISK_PER_TRADE_PCT * 100,
        config.DAILY_MAX_DRAWDOWN_PCT * 100,
    )
    log.info("=" * 60)

    if not config.BINANCE_API_KEY or not config.BINANCE_SECRET_KEY:
        log.warning(
            "BINANCE_API_KEY / BINANCE_SECRET_KEY not set — "
            "copy .env.example → .env and fill in your testnet keys."
        )

    guard = DrawdownGuard()

    if tg.is_configured():
        log.info("Telegram alerts enabled.")
        startup_balance: float | None = None
        try:
            startup_balance = fetch_usdt_balance()
        except ccxt.BaseError:
            pass
        if tg.send("✅ Telegram connected — EMA bot alerts are active."):
            tg.notify_startup(startup_balance)
            # Seed tracker so we don't re-alert the current candle on first loop.
            try:
                df = data.fetch_ohlcv()
                completed = data.get_completed_candles(df, count=1)
                global _last_telegram_candle_ts
                _last_telegram_candle_ts = completed.iloc[-1]["timestamp"]
            except Exception:
                pass
        else:
            log.warning(
                "Telegram is configured but the test message failed — "
                "check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            )
    else:
        log.info(
            "Telegram alerts disabled — set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in .env to enable."
        )

    while True:
        try:
            run_iteration(guard)
        except KeyboardInterrupt:
            log.info("Shutdown requested — exiting.")
            tg.notify_shutdown()
            break
        except Exception as exc:
            log.exception("Unexpected error in main loop")
            tg.notify_error("Unexpected error", str(exc))

        log.info("Sleeping %d seconds…", LOOP_INTERVAL_SEC)
        time.sleep(LOOP_INTERVAL_SEC)


if __name__ == "__main__":
    main()
