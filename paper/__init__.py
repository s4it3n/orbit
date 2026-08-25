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


def metrics_from_account(account: dict[str, Any]) -> dict[str, float]:
    initial = float(account.get("initial_capital") or 0.0) or 1.0
    curve = account.get("equity_curve") or []
    equities = [float(p.get("equity") or initial) for p in curve if p.get("equity") is not None]
    equity = float(account.get("cash") or initial)
    position = account.get("position")
    if position and equities:
        equity = equities[-1]
    elif equities:
        equity = equities[-1]
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
        "equity_usdt": round(equity, 2),
    }
