"""Shared paper-trading account helpers (local test money, no broker)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_account(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    merged = dict(defaults)
                    merged.update(raw)
                    return merged
            except (OSError, json.JSONDecodeError):
                pass
        return dict(defaults)


def save_account(path: Path, account: dict[str, Any]) -> None:
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(account, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)


def append_log(account: dict[str, Any], message: str, level: str = "INFO") -> None:
    logs = list(account.get("logs") or [])
    logs.append({"time": utc_now(), "level": level, "message": message})
    account["logs"] = logs[-80:]


def append_equity(account: dict[str, Any], equity: float, ts: str | None = None) -> None:
    curve = list(account.get("equity_curve") or [])
    curve.append({"timestamp": ts or utc_now(), "equity": float(equity)})
    account["equity_curve"] = curve[-500:]


def scale_paper_account(
    account: dict[str, Any],
    *,
    new_initial: float,
    old_initial: float | None = None,
) -> dict[str, Any]:
    """Proportionally resize cash, lots, trade PnL, and equity history.

    Keeps trade count and prices; only notionals / quantities / dollar PnL move.
    """
    stored = float(old_initial if old_initial is not None else (account.get("initial_capital") or 0.0))
    target = float(new_initial)
    if stored <= 0 or target <= 0:
        return account
    if abs(stored - target) < 1e-9:
        return account
    scale = target / stored
    out = dict(account)
    out["initial_capital"] = target
    if out.get("cash") is not None:
        out["cash"] = float(out["cash"]) * scale
    lot = out.get("position")
    if isinstance(lot, dict) and lot.get("qty") is not None:
        lot = dict(lot)
        lot["qty"] = float(lot["qty"]) * scale
        out["position"] = lot
    trades = []
    for trade in list(out.get("trades") or []):
        row = dict(trade)
        if row.get("quantity") is not None:
            row["quantity"] = float(row["quantity"]) * scale
        if row.get("pnl_usdt") is not None:
            row["pnl_usdt"] = float(row["pnl_usdt"]) * scale
        trades.append(row)
    out["trades"] = trades
    curve = []
    for point in list(out.get("equity_curve") or []):
        row = dict(point)
        if row.get("equity") is not None:
            row["equity"] = float(row["equity"]) * scale
        curve.append(row)
    out["equity_curve"] = curve
    return out


def equity_snapshot(account: dict[str, Any]) -> dict[str, float]:
    """Split idle cash vs total marked equity (incl. open trades)."""
    initial = float(account.get("initial_capital") or 0.0) or 1.0
    cash = float(account.get("cash") if account.get("cash") is not None else initial)
    curve = account.get("equity_curve") or []
    equities = [float(p.get("equity")) for p in curve if p.get("equity") is not None]
    marked = round(equities[-1] if equities else cash, 2)
    lot = account.get("position")
    if lot:
        qty = float(lot.get("qty") or 0.0)
        entry = float(lot.get("entry") or 0.0)
        # CFD ledgers keep cash flat and add unrealized into equity.
        unrealized = round(marked - round(cash, 2), 2)
        side = str(lot.get("side") or "long")
        if qty > 0 and entry > 0:
            # Mark value of the open lot (capital tied up in the running trade).
            if side == "short":
                invested = round(qty * entry - unrealized, 2)
            else:
                invested = round(qty * entry + unrealized, 2)
            invested = max(0.0, invested)
        else:
            invested = 0.0
        free = round(max(0.0, marked - invested), 2)
        open_pnl = unrealized
    else:
        free = marked
        open_pnl = 0.0
    return {
        "cash_usdt": free,
        "equity_usdt": marked,
        "open_pnl_usdt": open_pnl,
    }


def metrics_from_account(account: dict[str, Any]) -> dict[str, float]:
    initial = float(account.get("initial_capital") or 0.0) or 1.0
    snap = equity_snapshot(account)
    equity = snap["equity_usdt"]
    cash = snap["cash_usdt"]
    curve = account.get("equity_curve") or []
    equities = [float(p.get("equity") or initial) for p in curve if p.get("equity") is not None]
    if not equities:
        equities = [equity]
    total = (equity / initial - 1.0) * 100.0
    peak = equities[0] if equities else equity
    max_dd = 0.0
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            max_dd = min(max_dd, value / peak - 1.0)
    trades = list(account.get("trades") or [])
    pnls = [float(t.get("pnl_usdt") or 0.0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    return {
        "total_return_pct": round(total, 2),
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "win_rate_pct": round(len(wins) / len(pnls) * 100.0, 1) if pnls else 0.0,
        "profit_factor": round(sum(wins) / sum(losses), 2) if losses else (10.0 if wins else 0.0),
        "trade_count": len(pnls),
        "cash_usdt": cash,
        "equity_usdt": equity,
        "open_pnl_usdt": snap["open_pnl_usdt"],
    }
