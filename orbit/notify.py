"""Telegram alerts for trades and material failures.

Every filled trade names the bot, then shows all three paper books and the
combined desk equity / P&L. Daily digests are not sent.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from . import config, data

log = logging.getLogger("orbit.telegram")

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
ROOT = Path(__file__).resolve().parent.parent

_EXIT_LABELS = {
    "take_profit": "take profit",
    "trailing_stop": "trail stop",
    "initial_stop": "initial stop",
    "equity_lock": "session lock",
    "market_shock": "BTC shock",
    "regime_risk_off": "BTC risk-off",
    "heat": "heat reduce",
    "end_of_test": "flat",
    "time_stop": "time stop",
    "stop": "stop",
    "session_reset": "session reset",
}

CRYPTO_BOT = "Crypto"
GOLD_BOT = "Gold"
MNQ_BOT = "MNQ"

_STATE_FILES = {
    CRYPTO_BOT: ROOT / "orbit_state.json",
    GOLD_BOT: ROOT / "gold_state.json",
    MNQ_BOT: ROOT / "mnq_state.json",
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


def _starting_book(bot: str) -> float:
    crypto = float(config.ORBIT_PAPER_EQUITY)
    if bot == CRYPTO_BOT:
        return crypto
    if bot == GOLD_BOT:
        return float(os.getenv("GOLD_PAPER_EQUITY", str(crypto)))
    if bot == MNQ_BOT:
        return float(os.getenv("MNQ_PAPER_EQUITY", str(crypto)))
    return crypto


def paper_equity(value: float | None = None) -> float:
    """Sanitize crypto balances for Telegram.

    Never show the Binance testnet faucet (~$10k). Legitimate paper equity
    from a bot ledger (which can move above the starting $1k) is left intact.
    """
    cap = float(config.ORBIT_PAPER_EQUITY)
    if value is None:
        try:
            from . import state as bot_state

            live = bot_state.load_state().get("equity_usdt")
            if live is not None:
                return float(live)
        except Exception:
            pass
        return cap
    v = float(value)
    # Raw testnet faucet / uncapped exchange balance — not a paper book.
    if v >= max(cap * 2.5, 2500.0):
        return cap
    return v


def _equity_from_file(path: Path, *, fallback: float) -> float:
    try:
        if not path.exists():
            return fallback
        raw = json.loads(path.read_text(encoding="utf-8"))
        value = raw.get("equity_usdt")
        if value is None:
            return fallback
        return float(value)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return fallback


def desk_books(*, override: dict[str, float] | None = None) -> dict[str, float]:
    """Current paper equity for Crypto / Gold / MNQ."""
    books = {
        CRYPTO_BOT: paper_equity(
            _equity_from_file(_STATE_FILES[CRYPTO_BOT], fallback=_starting_book(CRYPTO_BOT))
        ),
        GOLD_BOT: _equity_from_file(
            _STATE_FILES[GOLD_BOT], fallback=_starting_book(GOLD_BOT)
        ),
        MNQ_BOT: _equity_from_file(
            _STATE_FILES[MNQ_BOT], fallback=_starting_book(MNQ_BOT)
        ),
    }
    if override:
        for bot, value in override.items():
            if bot == CRYPTO_BOT:
                books[bot] = paper_equity(value)
            else:
                books[bot] = float(value)
    return books


def format_desk_block(
    books: dict[str, float] | None = None,
    *,
    override: dict[str, float] | None = None,
) -> str:
    books = books or desk_books(override=override)
    start = sum(_starting_book(bot) for bot in (CRYPTO_BOT, GOLD_BOT, MNQ_BOT))
    total = sum(float(books[bot]) for bot in (CRYPTO_BOT, GOLD_BOT, MNQ_BOT))
    pnl = total - start
    sign = "+" if pnl >= 0 else "−"
    return (
        f"Crypto  {_usdt(books[CRYPTO_BOT])}\n"
        f"Gold    {_usdt(books[GOLD_BOT])}\n"
        f"MNQ     {_usdt(books[MNQ_BOT])}\n"
        f"desk    {_usdt(total)}  ({sign}{_usdt(abs(pnl))})"
    )


def format_startup(balance: float | None = None) -> str:
    override = {CRYPTO_BOT: paper_equity(balance)} if balance is not None else None
    return (
        f"<b>Orbit · online</b>\n"
        f"paper · 3 bots\n"
        f"{format_desk_block(override=override)}"
    )


def format_entry(
    position: dict,
    *,
    equity: float | None = None,
    bot: str = CRYPTO_BOT,
) -> str:
    symbol = str(position.get("symbol") or "?")
    qty = float(position.get("quantity") or 0.0)
    fill = float(position.get("entry_price") or 0.0)
    stop = float(position.get("initial_stop") or 0.0)
    override = {bot: float(equity)} if equity is not None else None
    return "\n".join([
        f"<b>{bot} · buy</b>  {_coin(symbol)}",
        f"{qty:.4g} @ {_px(fill)}",
        f"stop  {_px(stop)}",
        format_desk_block(override=override),
    ])


def format_exit(
    symbol: str,
    quantity: float,
    price: float,
    pnl: float,
    reason: str,
    *,
    equity: float | None = None,
    bot: str = CRYPTO_BOT,
) -> str:
    label = _EXIT_LABELS.get(reason, reason.replace("_", " "))
    title = "take profit" if reason == "take_profit" else "sell"
    sign = "+" if pnl >= 0 else "−"
    override = {bot: float(equity)} if equity is not None else None
    return "\n".join([
        f"<b>{bot} · {title}</b>  {_coin(symbol)}",
        f"{sign}{_usdt(abs(pnl))} USDT",
        f"{quantity:.4g} @ {_px(price)}",
        label,
        format_desk_block(override=override),
    ])


def format_drawdown(drawdown_pct: float, balance: float) -> str:
    limit = config.DAILY_MAX_DRAWDOWN_PCT * 100
    return (
        f"<b>{CRYPTO_BOT} · halted</b>\n"
        f"daily loss  {drawdown_pct * 100:.1f}%  (limit {limit:.0f}%)\n"
        f"{format_desk_block(override={CRYPTO_BOT: paper_equity(balance)})}\n"
        f"paused until next UTC day"
    )


def format_order_error(side: str, error: str) -> str:
    clipped = error.strip().replace("\n", " ")[:240]
    return f"<b>{CRYPTO_BOT} · order failed</b>  {side}\n<code>{clipped}</code>"


def format_error(title: str, detail: str) -> str:
    clipped = detail.strip().replace("\n", " ")[:240]
    return f"<b>{CRYPTO_BOT} · {title}</b>\n<code>{clipped}</code>"


def format_daily(
    *,
    candle_time: str,
    risk_on: bool,
    held: str | None,
    top: str | None,
    equity: float,
) -> str:
    # Kept for tests / manual use — not sent by the live loop anymore.
    regime = "BTC risk-on" if risk_on else "BTC risk-off"
    held_name = _coin(held) if held else "cash"
    extra = ""
    if top and (not held or top != held):
        extra = f"\nnext  {_coin(top)}"
    when = str(candle_time).replace("+00:00", " UTC")
    return (
        f"<b>{CRYPTO_BOT} · daily</b>  {when}\n"
        f"{format_desk_block(override={CRYPTO_BOT: paper_equity(equity)})}\n"
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
    equity: float | None = None,
) -> str:
    action = "buy" if side == "long" else "sell short" if side == "short" else side
    override = {bot: float(equity)} if equity is not None else None
    return "\n".join([
        f"<b>{bot} · {action}</b>  {symbol}",
        f"{qty:.4g} @ {_px(price)}",
        f"stop  {_px(stop)}",
        format_desk_block(override=override),
    ])


def format_paper_exit(
    bot: str,
    *,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    pnl: float,
    reason: str,
    equity: float | None = None,
) -> str:
    sign = "+" if pnl >= 0 else "−"
    label = _EXIT_LABELS.get(reason, reason.replace("_", " "))
    override = {bot: float(equity)} if equity is not None else None
    return "\n".join([
        f"<b>{bot} · closed</b>  {symbol}",
        f"{sign}{_usdt(abs(pnl))} USDT",
        f"{side} {qty:.4g} @ {_px(price)}",
        label,
        format_desk_block(override=override),
    ])


def notify_paper_entry(
    bot: str,
    *,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    stop: float,
    equity: float | None = None,
) -> None:
    send(
        format_paper_entry(
            bot, side=side, symbol=symbol, qty=qty, price=price, stop=stop, equity=equity
        )
    )


def notify_paper_exit(
    bot: str,
    *,
    side: str,
    symbol: str,
    qty: float,
    price: float,
    pnl: float,
    reason: str,
    equity: float | None = None,
) -> None:
    send(
        format_paper_exit(
            bot,
            side=side,
            symbol=symbol,
            qty=qty,
            price=price,
            pnl=pnl,
            reason=reason,
            equity=equity,
        )
    )


def format_deploy(sha: str, branch: str) -> str:
    short = sha[:7] if sha else "?"
    return f"<b>Orbit · updated</b>\n<code>{branch}</code>  {short}"


def notify_startup(balance: float | None = None) -> None:
    send(format_startup(balance))


def notify_entry(position: dict, *, equity: float | None = None) -> None:
    send(format_entry(position, equity=equity, bot=CRYPTO_BOT))


def notify_exit(
    symbol: str,
    quantity: float,
    price: float,
    pnl: float,
    reason: str,
    *,
    equity: float | None = None,
) -> None:
    send(
        format_exit(
            symbol, quantity, price, pnl, reason, equity=equity, bot=CRYPTO_BOT
        )
    )


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
    # Intentionally no-op: trade fills are the useful alerts.
    return


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
