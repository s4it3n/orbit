"""
Telegram notification helper.

Sends alerts for important bot events via the Telegram Bot API.
Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env file.
If either is missing, all send calls are silently skipped.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

import config
import strategy

log = logging.getLogger("ema-bot.telegram")

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_configured() -> bool:
    """Return True when both token and chat ID are set."""
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def send(message: str) -> bool:
    """
    Send a plain-text/HTML message to the configured Telegram chat.

    Returns True on success, False if disabled or the API call failed.
    """
    if not is_configured():
        return False

    url = _API_URL.format(token=config.TELEGRAM_BOT_TOKEN)
    payload = json.dumps(
        {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status == 200:
                return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        log.error("Telegram API HTTP %s: %s", exc.code, body)
    except urllib.error.URLError as exc:
        log.error("Telegram request failed: %s", exc.reason)

    return False


def notify_startup(balance: float | None = None) -> None:
    """Bot started — send config summary and optional balance."""
    balance_line = (
        f"\n💰 Balance: <b>{balance:,.2f} USDT</b>" if balance is not None else ""
    )
    send(
        "🚀 <b>EMA Bot started</b> (Binance sandbox)\n"
        f"📊 {config.TRADING_SYMBOL} · {config.TIMEFRAME}\n"
        f"⚖️ Risk/trade: {config.RISK_PER_TRADE_PCT * 100:.0f}% · "
        f"Max daily DD: {config.DAILY_MAX_DRAWDOWN_PCT * 100:.0f}%"
        f"{balance_line}"
    )


def notify_new_day(balance: float) -> None:
    """New UTC trading day — reset drawdown tracker."""
    send(
        "📅 <b>New trading day</b>\n"
        f"Start-of-day balance: <b>{balance:,.2f} USDT</b>"
    )


def notify_signal(
    side: str,
    close: float,
    ema_fast: float,
    ema_slow: float,
    atr: float,
) -> None:
    """EMA crossover signal detected."""
    emoji = "🟢" if side == "BUY" else "🔴"
    send(
        f"{emoji} <b>Signal: {side}</b>\n"
        f"Close: <code>{close:,.2f}</code>\n"
        f"EMA{config.EMA_FAST}: <code>{ema_fast:,.2f}</code> · "
        f"EMA{config.EMA_SLOW}: <code>{ema_slow:,.2f}</code>\n"
        f"ATR: <code>{atr:,.2f}</code>"
    )


def notify_order(plan: strategy.TradePlan, order_id: str, status: str) -> None:
    """Order placed successfully on sandbox."""
    emoji = "🟢" if plan.side == "BUY" else "🔴"
    send(
        f"{emoji} <b>Order executed</b> [{plan.side}]\n"
        f"Qty: <code>{plan.quantity:.8f}</code>\n"
        f"Entry ≈ <code>{plan.entry_price:,.2f}</code>\n"
        f"SL: <code>{plan.stop_loss:,.2f}</code> · "
        f"TP: <code>{plan.take_profit:,.2f}</code>\n"
        f"Order ID: <code>{order_id}</code> · Status: {status}"
    )


def notify_order_error(side: str, error: str) -> None:
    """Order rejected or failed."""
    send(f"❌ <b>Order failed</b> [{side}]\n<code>{error}</code>")


def notify_drawdown_kill(drawdown_pct: float, balance: float) -> None:
    """Daily drawdown limit hit — trading paused."""
    send(
        "🛑 <b>Daily drawdown limit hit</b>\n"
        f"Loss: <b>{drawdown_pct * 100:.2f}%</b> "
        f"(limit {config.DAILY_MAX_DRAWDOWN_PCT * 100:.0f}%)\n"
        f"Balance: <code>{balance:,.2f} USDT</code>\n"
        "Trading paused until next UTC day."
    )


def notify_error(title: str, detail: str) -> None:
    """Generic error alert."""
    send(f"⚠️ <b>{title}</b>\n<code>{detail}</code>")


def notify_shutdown() -> None:
    """Bot stopped by user."""
    send("⏹️ <b>EMA Bot stopped</b>")


def notify_hourly_status(
    candle_time: str,
    close: float,
    ema_fast: float,
    ema_slow: float,
    atr: float,
    balance: float,
) -> None:
    """Send a summary when a new hourly candle closes (no trade signal)."""
    if ema_fast > ema_slow:
        trend = "EMA20 above EMA50 (bullish)"
    elif ema_fast < ema_slow:
        trend = "EMA20 below EMA50 (bearish)"
    else:
        trend = "EMA20 = EMA50 (neutral)"

    send(
        "📊 <b>New candle closed</b>\n"
        f"🕐 {candle_time}\n"
        f"Close: <code>{close:,.2f}</code>\n"
        f"EMA{config.EMA_FAST}: <code>{ema_fast:,.2f}</code> · "
        f"EMA{config.EMA_SLOW}: <code>{ema_slow:,.2f}</code>\n"
        f"ATR: <code>{atr:,.2f}</code>\n"
        f"Trend: {trend}\n"
        f"No crossover — watching for signal\n"
        f"💰 Balance: <code>{balance:,.2f} USDT</code>"
    )
