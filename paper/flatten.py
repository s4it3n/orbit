"""Manual flatten helpers — close open lots and pause so they do not reopen."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def flatten_bot(bot_id: str, *, pause: bool = True) -> dict[str, Any]:
    """Flatten one desk. Crypto sells on testnet; gold/QQQ close paper lots."""
    bot_id = str(bot_id or "").lower().strip()
    if bot_id == "orbit":
        return _flatten_crypto(pause=pause)
    if bot_id == "gold":
        return _flatten_yahoo("gold", pause=pause)
    if bot_id == "mnq":
        return _flatten_yahoo("mnq", pause=pause)
    return {"ok": False, "bot_id": bot_id, "message": "Unknown bot"}


def _summarize(bots: dict[str, Any]) -> str:
    bits: list[str] = []
    labels = {"orbit": "Crypto", "gold": "Gold", "mnq": "QQQ"}
    for bid, row in bots.items():
        name = labels.get(bid, bid)
        closed = row.get("closed")
        if isinstance(closed, list) and closed:
            syms = ", ".join(
                f"{c.get('symbol')}@{c.get('price')}" for c in closed if isinstance(c, dict)
            )
            bits.append(f"{name}: sold {syms}")
        elif isinstance(closed, dict) and closed:
            bits.append(
                f"{name}: closed {closed.get('side')} {closed.get('qty')} @ {closed.get('price')}"
            )
        else:
            bits.append(f"{name}: already flat")
    return "; ".join(bits)


def flatten_all(*, pause: bool = True) -> dict[str, Any]:
    bots = {
        "orbit": flatten_bot("orbit", pause=pause),
        "gold": flatten_bot("gold", pause=pause),
        "mnq": flatten_bot("mnq", pause=pause),
    }
    ok = all(bool(row.get("ok")) for row in bots.values())
    summary = _summarize(bots)
    suffix = " All bots paused — Start each desk to resume." if pause else ""
    return {
        "ok": ok,
        "bots": bots,
        "paused": pause,
        "message": summary + suffix,
        "summary": summary,
    }


def _flatten_crypto(*, pause: bool) -> dict[str, Any]:
    from orbit import config, controller
    from orbit import engine
    from orbit import exporter as orbit_exporter
    from orbit import state as bot_state

    errors: list[str] = []
    closed: list[dict[str, Any]] = []

    if pause:
        try:
            bot_state.save_settings({"bot_enabled": False})
            config.reload_settings()
            controller.stop()
            bot_state.update_state(
                trading_paused=True,
                pause_reason="manual_flatten",
            )
            bot_state.append_operation(
                "FLATTEN",
                "Manual flatten — crypto paused (will not reopen until Start)",
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"pause: {exc}")

    live = bot_state.load_state()
    book = list(live.get("positions") or [])
    pos = live.get("position") or {}
    if not book and str(pos.get("status") or "") == "long" and pos.get("symbol"):
        book = [dict(pos)]

    if not book:
        try:
            orbit_exporter.export_state()
        except Exception:
            pass
        return {
            "ok": True,
            "bot_id": "orbit",
            "closed": [],
            "paused": pause,
            "message": "Already flat",
            "errors": errors,
        }

    remaining = list(book)
    candle_ts = datetime.now(timezone.utc).isoformat()
    try:
        config.exchange.load_markets()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"markets: {exc}")

    for position in list(remaining):
        symbol = str(position.get("symbol") or "")
        if not symbol:
            remaining = [p for p in remaining if p is not position]
            continue
        try:
            ticker = config.exchange.fetch_ticker(symbol)
            price = float(
                ticker.get("last")
                or position.get("entry_price")
                or 0.0
            )
            if price <= 0:
                raise ValueError("no mark price")
            before = len(remaining)
            remaining = engine._exit_long(
                position, price, "manual_flatten", candle_ts, remaining
            )
            if len(remaining) < before:
                closed.append({"symbol": symbol, "price": price})
            else:
                errors.append(f"{symbol}: still open after exit attempt")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{symbol}: {exc}")

    try:
        orbit_exporter.export_state()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"export: {exc}")

    return {
        "ok": len(errors) == 0 or bool(closed),
        "bot_id": "orbit",
        "closed": closed,
        "paused": pause,
        "still_open": [
            str(p.get("symbol")) for p in remaining if p.get("symbol")
        ],
        "errors": errors,
        "message": (
            f"Closed {len(closed)} lot(s)" if closed else "No lots closed"
        ),
    }


def _flatten_yahoo(bot_id: str, *, pause: bool) -> dict[str, Any]:
    from paper import loops as paper_loops

    if bot_id == "gold":
        from gold_bot import live as live_mod
    else:
        from mnq_bot import live as live_mod

    errors: list[str] = []
    closed: dict[str, Any] | None = None

    if pause:
        try:
            live_mod.set_enabled(False)
            paper_loops.stop(bot_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"pause: {exc}")

    try:
        result = live_mod.flatten_now(reason="manual_flatten")
        closed = result.get("closed")
        if result.get("error"):
            errors.append(str(result["error"]))
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        return {
            "ok": False,
            "bot_id": bot_id,
            "closed": None,
            "paused": pause,
            "errors": errors,
            "message": str(exc),
        }

    return {
        "ok": len(errors) == 0,
        "bot_id": bot_id,
        "closed": closed,
        "paused": pause,
        "errors": errors,
        "message": (
            "Closed open lot" if closed else "Already flat"
        ),
    }
