"""Telegram alerts for material Orbit events only.

Sends: entries, exits, daily bar digest, drawdown halt, order/system failures,
and deploy notices. Routine loop noise (trail ticks, rotations, new-day pings)
stays in logs.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from . import config, data

log = logging.getLogger("orbit.telegram")

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

_EXIT_LABELS = {
    "take_profit": "take profit",
    "trailing_stop": "trail stop",
    "initial_stop": "initial stop",
    "equity_lock": "session lock",
    "market_shock": "BTC shock",
    "regime_risk_off": "BTC risk-off",
    "heat": "heat reduce",
    "end_of_test": "flat",
}


def is_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def send(message: str) -> bool:
    if not is_configured() or not message.strip():
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
            return response.status == 200
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        log.error("Telegram API HTTP %s: %s", exc.code, body)
    except urllib.error.URLError as exc:
        log.error("Telegram request failed: %s", exc.reason)
    return False


def _px(value: float) -> str:
    return data.round_price(float(value))


def _usdt(value: float, signed: bool = False) -> str:
    if signed:
        return f"{value:+,.2f}"
    return f"{value:,.2f}"


def _coin(symbol: str) -> str:
    return (symbol or "?").replace("/USDT", "")


def format_startup(balance: float | None = None) -> str:
    # Always show the paper book (~$1k), never the raw testnet faucet balance.
    if balance is not None:
        paper = min(float(balance), float(config.ORBIT_PAPER_EQUITY))
        equity = f"\npaper equity  {_usdt(paper)} USDT"
    else:
        equity = f"\npaper equity  {_usdt(float(config.ORBIT_PAPER_EQUITY))} USDT"
    return f"<b>Orbit · online</b>\npaper · Binance testnet{equity}"


def format_entry(position: dict) -> str:
    symbol = str(position.get("symbol") or "?")
    qty = float(position.get("quantity") or 0.0)
    fill = float(position.get("entry_price") or 0.0)
    stop = float(position.get("initial_stop") or 0.0)
    return (
        f"<b>Orbit · long</b>  {_coin(symbol)}\n"
        f"{qty:.4g} @ {_px(fill)}\n"
        f"stop  {_px(stop)}"
    )


def format_exit(
    symbol: str,
    quantity: float,
    price: float,
    pnl: float,
    reason: str,
) -> str:
    label = _EXIT_LABELS.get(reason, reason.replace("_", " "))
    title = "take profit" if reason == "take_profit" else "closed"
    sign = "+" if pnl >= 0 else "−"
    return (
        f"<b>Orbit · {title}</b>  {_coin(symbol)}\n"
        f"{sign}{_usdt(abs(pnl))} USDT\n"
        f"{quantity:.4g} @ {_px(price)}\n"
        f"{label}"
    )


def format_drawdown(drawdown_pct: float, balance: float) -> str:
    limit = config.DAILY_MAX_DRAWDOWN_PCT * 100
    paper = min(float(balance), float(config.ORBIT_PAPER_EQUITY))
    return (
        f"<b>Orbit · halted</b>\n"
        f"daily loss  {drawdown_pct * 100:.1f}%  (limit {limit:.0f}%)\n"
        f"paper equity  {_usdt(paper)} USDT\n"
        f"paused until next UTC day"
    )


def format_order_error(side: str, error: str) -> str:
    clipped = error.strip().replace("\n", " ")[:240]
    return f"<b>Orbit · order failed</b>  {side}\n<code>{clipped}</code>"


def format_error(title: str, detail: str) -> str:
    clipped = detail.strip().replace("\n", " ")[:240]
    return f"<b>Orbit · {title}</b>\n<code>{clipped}</code>"


def format_daily(
    *,
    candle_time: str,
    risk_on: bool,
    held: str | None,
    top: str | None,
    equity: float,
) -> str:
    regime = "BTC risk-on" if risk_on else "BTC risk-off"
    held_name = _coin(held) if held else "cash"
    extra = ""
    if top and (not held or top != held):
        extra = f"\nnext  {_coin(top)}"
    when = str(candle_time).replace("+00:00", " UTC")
    paper = min(float(equity), float(config.ORBIT_PAPER_EQUITY))
    return (
        f"<b>Orbit · daily</b>  {when}\n"
        f"paper equity  {_usdt(paper)} USDT\n"
        f"{regime} · {held_name}"
        f"{extra}"
    )


def format_paper_entry(
    bot: str,
    *,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    stop: float,
) -> str:
    return (
        f"<b>{bot} · {side}</b>  {symbol}\n"
        f"{qty:.4g} @ {_px(price)}\n"
        f"stop  {_px(stop)}"
    )


def format_paper_exit(
    bot: str,
    *,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    pnl: float,
    reason: str,
) -> str:
    sign = "+" if pnl >= 0 else "−"
    return (
        f"<b>{bot} · closed</b>  {symbol}\n"
        f"{sign}{_usdt(abs(pnl))} USDT\n"
        f"{side} {qty:.4g} @ {_px(price)}\n"
        f"{reason.replace('_', ' ')}"
    )


def notify_paper_entry(
    bot: str,
    *,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    stop: float,
) -> None:
    send(format_paper_entry(bot, side=side, symbol=symbol, qty=qty, price=price, stop=stop))


def notify_paper_exit(
    bot: str,
    *,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    pnl: float,
    reason: str,
) -> None:
    send(
        format_paper_exit(
            bot, side=side, symbol=symbol, qty=qty, price=price, pnl=pnl, reason=reason
        )
    )


def format_deploy(sha: str, branch: str) -> str:
    short = sha[:7] if sha else "?"
    return f"<b>Orbit · updated</b>\n<code>{branch}</code>  {short}"


def notify_startup(balance: float | None = None) -> None:
    send(format_startup(balance))


def notify_entry(position: dict) -> None:
    send(format_entry(position))


def notify_exit(
    symbol: str,
    quantity: float,
    price: float,
    pnl: float,
    reason: str,
) -> None:
    send(format_exit(symbol, quantity, price, pnl, reason))


def notify_drawdown_kill(drawdown_pct: float, balance: float) -> None:
    send(format_drawdown(drawdown_pct, balance))


def notify_order_error(side: str, error: str) -> None:
    send(format_order_error(side, error))


def notify_error(title: str, detail: str) -> None:
    send(format_error(title, detail))


def notify_daily(
    *,
    candle_time: str,
    risk_on: bool,
    held: str | None,
    top: str | None,
    equity: float,
) -> None:
    send(format_daily(
        candle_time=candle_time,
        risk_on=risk_on,
        held=held,
        top=top,
        equity=equity,
    ))


def notify_deploy(sha: str, branch: str = "main") -> None:
    send(format_deploy(sha, branch))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Orbit Telegram helper.")
    parser.add_argument("--deploy", nargs=2, metavar=("SHA", "BRANCH"))
    args = parser.parse_args()
    if args.deploy:
        notify_deploy(args.deploy[0], args.deploy[1])


if __name__ == "__main__":
    main()
