"""Export a dashboard-facing snapshot to ``orbit_state.json`` each cycle."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import state as bot_state

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "orbit_state.json"

# Locked ACCEPTED 1D walk-forward headline metrics (stitched OOS).
ACCEPTED_METRICS = {
    "total_return_pct": 35.2,
    "sharpe_ratio": 0.50,
    "max_drawdown_pct": -18.9,
    "win_rate_pct": 64.2,
    "profit_factor": 1.34,
    "trade_count": 153,
}

BOT_NAME = "Orbit 1D Crypto Momentum"
BOT_ID = "orbit"
ASSET_CLASS = "Crypto Spot"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_from_live(live: dict[str, Any]) -> str:
    if live.get("bot_running") and live.get("trading_paused") is False and bot_state.load_settings().get(
        "bot_enabled"
    ):
        return "PAPER"
    if live.get("bot_running"):
        return "IDLE"
    return "IDLE"


def _position_payload(live: dict[str, Any]) -> dict[str, Any] | None:
    position = live.get("position") or {}
    if position.get("status") != "long" or not position.get("symbol"):
        symbols = live.get("active_symbols") or []
        if not symbols:
            return None
    symbol = position.get("symbol") or (live.get("active_symbols") or [None])[0]
    if not symbol:
        return None
    return {
        "symbol": symbol,
        "side": "long",
        "quantity": float(position.get("quantity") or 0.0),
        "entry_price": position.get("entry_price"),
        "stop_loss": position.get("trailing_stop") or position.get("stop_loss"),
        "bars_held": int(position.get("bars_held") or 0),
    }


def _equity_curve_from_ops(live: dict[str, Any]) -> list[dict[str, Any]]:
    equity = live.get("equity_usdt")
    if equity is None:
        return []
    return [{"timestamp": live.get("last_updated") or _now_iso(), "equity": float(equity)}]


def _recent_trades(live: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for op in live.get("operations") or []:
        if op.get("type") not in {"ENTRY", "EXIT", "TAKE_PROFIT"}:
            continue
        rows.append({
            "time": op.get("time"),
            "type": op.get("type"),
            "detail": op.get("detail"),
            "symbol": op.get("symbol"),
            "pnl_usdt": op.get("pnl_usdt"),
        })
        if len(rows) >= limit:
            break
    return rows


def build_export_payload(live: dict[str, Any] | None = None) -> dict[str, Any]:
    live = live if live is not None else bot_state.load_state()
    settings = bot_state.load_settings()
    status = "ACTIVE" if settings.get("bot_enabled") and live.get("bot_running") else "IDLE"
    if status == "ACTIVE":
        status = "PAPER"
    return {
        "bot_id": BOT_ID,
        "bot_name": BOT_NAME,
        "asset_class": ASSET_CLASS,
        "timeframe": "1d",
        "status": status,
        "updated_at": _now_iso(),
        "total_return_pct": ACCEPTED_METRICS["total_return_pct"],
        "sharpe_ratio": ACCEPTED_METRICS["sharpe_ratio"],
        "max_drawdown_pct": ACCEPTED_METRICS["max_drawdown_pct"],
        "win_rate_pct": ACCEPTED_METRICS["win_rate_pct"],
        "profit_factor": ACCEPTED_METRICS["profit_factor"],
        "trade_count": ACCEPTED_METRICS["trade_count"],
        "current_position": _position_payload(live),
        "equity_usdt": live.get("equity_usdt"),
        "equity_curve": _equity_curve_from_ops(live),
        "recent_trades": _recent_trades(live),
        "logs": (live.get("logs") or [])[-50:],
        "regime": live.get("regime") or {},
        "accepted": True,
        "acceptance_note": "Walk-forward ACCEPTED (9/9 Gates Passed)",
    }


def export_state(live: dict[str, Any] | None = None, path: Path | None = None) -> dict[str, Any]:
    payload = build_export_payload(live)
    target = path or STATE_PATH
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload
