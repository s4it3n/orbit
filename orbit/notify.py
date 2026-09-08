"""Telegram alerts for trades, material failures, and a daily desk digest.

Every filled trade names the bot, then shows all three paper books and the
combined desk equity / P&L. Once per UTC day (after TELEGRAM_DAILY_HOUR) a
short summary covers day P&L, closed trades, and open positions.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
MNQ_BOT = "QQQ"

_STATE_FILES = {
    CRYPTO_BOT: ROOT / "orbit_state.json",
    GOLD_BOT: ROOT / "gold_state.json",
    MNQ_BOT: ROOT / "mnq_state.json",
}
_LIVE_FILES = {
    CRYPTO_BOT: ROOT / "bot_state.json",
    GOLD_BOT: ROOT / "gold_live.json",
    MNQ_BOT: ROOT / "mnq_live.json",
}
_DAILY_PATH = ROOT / "desk_daily.json"
_DAILY_LOCK = threading.Lock()

# Send once per UTC day at/after this hour (default 21:00 UTC).
TELEGRAM_DAILY_HOUR = int(os.getenv("TELEGRAM_DAILY_HOUR", "21"))


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
    from a bot ledger (which can move above the starting paper book) is left intact.
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
        f"QQQ     {_usdt(books[MNQ_BOT])}\n"
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
    """Legacy crypto-only daily line (kept for older tests / callers)."""
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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _trades_closed_on(day: str) -> list[dict[str, Any]]:
    """Closed Gold/MNQ trades + crypto EXIT ops for a UTC calendar day."""
    rows: list[dict[str, Any]] = []
    for bot, path in (
        (GOLD_BOT, _LIVE_FILES[GOLD_BOT]),
        (MNQ_BOT, _LIVE_FILES[MNQ_BOT]),
    ):
        live = _load_json(path)
        for trade in list(live.get("trades") or []):
            ts = _parse_ts(trade.get("exit_time"))
            if ts is None or ts.date().isoformat() != day:
                continue
            rows.append({
                "bot": bot,
                "symbol": trade.get("symbol") or "?",
                "pnl": float(trade.get("pnl_usdt") or 0.0),
                "reason": trade.get("reason") or "closed",
            })
    crypto = _load_json(_LIVE_FILES[CRYPTO_BOT])
    for op in list(crypto.get("operations") or []):
        if op.get("type") not in {"EXIT", "TAKE_PROFIT"}:
            continue
        ts = _parse_ts(op.get("time"))
        if ts is None or ts.date().isoformat() != day:
            continue
        try:
            pnl_f = float(op.get("pnl_usdt") or 0.0)
        except (TypeError, ValueError):
            pnl_f = 0.0
        symbol = op.get("symbol") or "?"
        rows.append({
            "bot": CRYPTO_BOT,
            "symbol": _coin(str(symbol)),
            "pnl": pnl_f,
            "reason": str(op.get("type") or "closed").lower(),
        })
    return rows


def _open_positions() -> list[str]:
    lines: list[str] = []
    crypto = _load_json(_LIVE_FILES[CRYPTO_BOT])
    pos = crypto.get("position") or {}
    if pos.get("status") == "long" and pos.get("symbol"):
        lines.append(f"Crypto  long {_coin(str(pos['symbol']))}")
    for bot, path in ((GOLD_BOT, _LIVE_FILES[GOLD_BOT]), (MNQ_BOT, _LIVE_FILES[MNQ_BOT])):
        live = _load_json(path)
        lot = live.get("position")
        if isinstance(lot, dict) and lot.get("side"):
            sym = "XAU/USD" if bot == GOLD_BOT else "QQQ"
            lines.append(f"{bot}  {lot['side']} {sym}")
    return lines


def _crypto_regime_line() -> str:
    live = _load_json(_LIVE_FILES[CRYPTO_BOT])
    regime = live.get("regime") or {}
    if regime.get("market_shock"):
        return "BTC shock"
    if regime.get("risk_on") is True:
        return "BTC risk-on"
    if regime.get("risk_on") is False:
        return "BTC risk-off"
    exported = _load_json(_STATE_FILES[CRYPTO_BOT])
    reg2 = exported.get("regime") or {}
    if reg2.get("risk_on") is True:
        return "BTC risk-on"
    if reg2.get("risk_on") is False:
        return "BTC risk-off"
    return "BTC —"


def format_desk_daily(
    *,
    day: str,
    books: dict[str, float],
    open_books: dict[str, float],
    trades: list[dict[str, Any]],
    positions: list[str],
    regime: str,
) -> str:
    """End-of-day desk summary for Telegram."""
    start = sum(float(open_books.get(b) or _starting_book(b)) for b in (CRYPTO_BOT, GOLD_BOT, MNQ_BOT))
    total = sum(float(books[b]) for b in (CRYPTO_BOT, GOLD_BOT, MNQ_BOT))
    day_pnl = total - start
    sign = "+" if day_pnl >= 0 else "−"
    lines = [
        f"<b>Orbit · daily</b>  {day} UTC",
        f"Crypto  {_usdt(books[CRYPTO_BOT])}  ({_usdt(books[CRYPTO_BOT] - float(open_books.get(CRYPTO_BOT, _starting_book(CRYPTO_BOT))), signed=True)})",
        f"Gold    {_usdt(books[GOLD_BOT])}  ({_usdt(books[GOLD_BOT] - float(open_books.get(GOLD_BOT, _starting_book(GOLD_BOT))), signed=True)})",
        f"QQQ     {_usdt(books[MNQ_BOT])}  ({_usdt(books[MNQ_BOT] - float(open_books.get(MNQ_BOT, _starting_book(MNQ_BOT))), signed=True)})",
        f"desk    {_usdt(total)}  ({sign}{_usdt(abs(day_pnl))} day)",
        regime,
    ]
    if trades:
        wins = sum(1 for t in trades if float(t.get("pnl") or 0) > 0)
        losses = sum(1 for t in trades if float(t.get("pnl") or 0) < 0)
        realized = sum(float(t.get("pnl") or 0) for t in trades)
        rsign = "+" if realized >= 0 else "−"
        lines.append(
            f"trades  {len(trades)} closed  ({wins}W/{losses}L)  "
            f"{rsign}{_usdt(abs(realized))} realized"
        )
        # Show up to 5 trade lines.
        for trade in trades[:5]:
            tsign = "+" if float(trade["pnl"]) >= 0 else "−"
            lines.append(
                f"· {trade['bot']} {_coin(str(trade['symbol']))}  "
                f"{tsign}{_usdt(abs(float(trade['pnl'])))}"
            )
        if len(trades) > 5:
            lines.append(f"· … +{len(trades) - 5} more")
    else:
        lines.append("trades  none closed")
    if positions:
        lines.append("open  " + " · ".join(positions))
    else:
        lines.append("open  flat")
    return "\n".join(lines)


def build_desk_daily(*, day: str | None = None) -> str:
    """Assemble today's digest from live ledgers."""
    now = datetime.now(timezone.utc)
    day = day or now.date().isoformat()
    books = desk_books()
    snap = _load_json(_DAILY_PATH)
    open_books = snap.get("open_books") if isinstance(snap.get("open_books"), dict) else {}
    # Normalize keys
    open_norm = {
        CRYPTO_BOT: float(open_books.get(CRYPTO_BOT, _starting_book(CRYPTO_BOT))),
        GOLD_BOT: float(open_books.get(GOLD_BOT, _starting_book(GOLD_BOT))),
        MNQ_BOT: float(open_books.get(MNQ_BOT, _starting_book(MNQ_BOT))),
    }
    return format_desk_daily(
        day=day,
        books=books,
        open_books=open_norm,
        trades=_trades_closed_on(day),
        positions=_open_positions(),
        regime=_crypto_regime_line(),
    )


def _save_daily_state(payload: dict[str, Any]) -> None:
    try:
        _DAILY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        log.error("Failed to write desk_daily.json: %s", exc)


def maybe_notify_daily_desk(*, force: bool = False) -> bool:
    """Send the desk daily digest once per UTC day after TELEGRAM_DAILY_HOUR.

    Safe to call from every bot loop. Returns True if a message was sent.
    """
    if not is_configured() and not force:
        return False
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    with _DAILY_LOCK:
        snap = _load_json(_DAILY_PATH)
        # Seed open-of-day books on first sight of a new UTC day.
        if snap.get("open_day") != today:
            books = desk_books()
            snap = {
                "open_day": today,
                "open_books": {
                    CRYPTO_BOT: books[CRYPTO_BOT],
                    GOLD_BOT: books[GOLD_BOT],
                    MNQ_BOT: books[MNQ_BOT],
                },
                "last_sent": snap.get("last_sent"),
            }
            _save_daily_state(snap)
        if not force:
            if snap.get("last_sent") == today:
                return False
            if now.hour < TELEGRAM_DAILY_HOUR:
                return False
        text = build_desk_daily(day=today)
        ok = send(text) if is_configured() else True
        if ok or force:
            snap["last_sent"] = today
            snap["last_text"] = text
            _save_daily_state(snap)
            log.info("Telegram daily desk digest sent for %s", today)
        return bool(ok)


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
    """Compatibility wrapper — prefer ``maybe_notify_daily_desk``."""
    maybe_notify_daily_desk()


def notify_deploy(sha: str, branch: str = "main") -> None:
    send(format_deploy(sha, branch))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Orbit Telegram helper.")
    parser.add_argument("--deploy", nargs=2, metavar=("SHA", "BRANCH"))
    parser.add_argument(
        "--daily",
        action="store_true",
        help="Send (or force) the desk daily digest now.",
    )
    parser.add_argument(
        "--force-daily",
        action="store_true",
        help="Send the desk daily digest even if already sent today.",
    )
    args = parser.parse_args()
    if args.deploy:
        notify_deploy(args.deploy[0], args.deploy[1])
    if args.daily or args.force_daily:
        maybe_notify_daily_desk(force=bool(args.force_daily or args.daily))


if __name__ == "__main__":
    main()
