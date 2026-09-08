"""Gold live paper loop — test money marked to Yahoo GC=F."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pandas as pd

from paper import (
    append_equity,
    append_log,
    load_account,
    metrics_from_account,
    save_account,
    scale_paper_account,
    utc_now,
)
from paper.costs import GOLD_COST_BPS, gold_fill_price, gold_side_cost
from paper.loops import is_running as loop_running

from . import strategy as gold_strategy
from . import settings as gold_settings
from .data import fetch_gold_hourly

ROOT = Path(__file__).resolve().parent.parent
ACCOUNT_PATH = ROOT / "gold_live.json"
STATE_PATH = ROOT / "gold_state.json"
WF_PATH = ROOT / "backtest_output" / "walk_forward_gold.json"

BOT_ID = "gold"
BOT_NAME = "Gold 1H Volatility Breakout"
ASSET_CLASS = "XAU/USD"
INITIAL_CAPITAL = float(os.getenv("GOLD_PAPER_EQUITY", os.getenv("ORBIT_PAPER_EQUITY", "100")))
COST_BPS = GOLD_COST_BPS
LOOP_INTERVAL_SEC = int(os.getenv("GOLD_LOOP_INTERVAL_SEC", "180"))
WARMUP_BARS = 320
LIVE_TAIL = 480

_DEFAULTS: dict[str, Any] = {
    "bot_id": BOT_ID,
    "enabled": True,
    "bot_running": False,
    "initial_capital": INITIAL_CAPITAL,
    "cash": INITIAL_CAPITAL,
    "position": None,
    "trades": [],
    "equity_curve": [{"timestamp": utc_now(), "equity": INITIAL_CAPITAL}],
    "logs": [],
    "last_processed_bar_ts": None,
}


def _fresh_defaults(*, enabled: bool = True, bot_running: bool = False) -> dict[str, Any]:
    return {
        "bot_id": BOT_ID,
        "enabled": enabled,
        "bot_running": bot_running,
        "initial_capital": INITIAL_CAPITAL,
        "cash": INITIAL_CAPITAL,
        "position": None,
        "trades": [],
        "equity_curve": [{"timestamp": utc_now(), "equity": INITIAL_CAPITAL}],
        "logs": [],
        "last_processed_bar_ts": None,
    }


def _ensure_paper_capital(account: dict[str, Any]) -> dict[str, Any]:
    stored = float(account.get("initial_capital") or 0.0)
    if stored <= 0:
        return _fresh_defaults(
            enabled=bool(account.get("enabled", True)),
            bot_running=bool(account.get("bot_running", False)),
        )
    if abs(stored - INITIAL_CAPITAL) < 1e-9:
        return account
    # Keep history: shrink/grow lots, PnL, and curve with the new paper book.
    scaled = scale_paper_account(account, new_initial=INITIAL_CAPITAL, old_initial=stored)
    append_log(
        scaled,
        f"Scaled paper account ${stored:.0f} → ${INITIAL_CAPITAL:.0f} (x{INITIAL_CAPITAL / stored:.4g})",
    )
    return scaled


def _load() -> dict[str, Any]:
    return _ensure_paper_capital(load_account(ACCOUNT_PATH, _DEFAULTS))


def _as_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _apply_cost(qty: float, price: float) -> float:
    return gold_side_cost(qty, price, cost_bps=COST_BPS)


def _mark(account: dict[str, Any], price: float) -> float:
    cash = float(account["cash"])
    lot = account.get("position")
    if not lot:
        return cash
    side = 1 if lot["side"] == "long" else -1
    return cash + (price - float(lot["entry"])) * float(lot["qty"]) * side


def _headline() -> dict[str, Any] | None:
    if not WF_PATH.exists():
        return None
    try:
        payload = json.loads(WF_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    agg = payload.get("aggregate") or {}
    if not agg:
        return None
    gates = payload.get("gates") or {}
    passed = sum(1 for value in gates.values() if value)
    return {
        "research_return_pct": round(float(agg.get("return_pct") or 0.0), 2),
        "research_sharpe": round(float(agg.get("sharpe") or 0.0), 2),
        "research_sharpe_ratio": round(float(agg.get("sharpe") or 0.0), 2),
        "research_max_drawdown_pct": round(float(agg.get("max_drawdown_pct") or 0.0), 2),
        "research_win_rate_pct": round(float(agg.get("win_rate_pct") or 0.0), 1),
        "research_profit_factor": round(float(agg.get("profit_factor") or 0.0), 2),
        "research_trade_count": int(agg.get("trade_count") or 0),
        "gates_passed": passed,
        "gates_total": len(gates),
        "accepted": bool(payload.get("accepted")),
        "acceptance_note": (
            f"Walk-forward {'ACCEPTED' if payload.get('accepted') else 'REJECTED'}"
            f" ({passed}/{len(gates)} gates)"
        ),
    }


def export_live_state(account: dict[str, Any] | None = None) -> dict[str, Any]:
    account = account or _load()
    metrics = metrics_from_account(account)
    running = bool(account.get("bot_running")) or loop_running(BOT_ID)
    enabled = bool(account.get("enabled", True))
    status = "PAPER" if running and enabled else ("IDLE" if not enabled else "PAPER")
    lot = account.get("position")
    current = None
    if lot:
        current = {
            "symbol": "XAU/USD",
            "side": lot["side"],
            "entry_price": lot["entry"],
            "stop": lot["stop"],
            "quantity": lot["qty"],
            "entry_time": lot["entry_time"],
        }
    headline = _headline() or {}
    payload = {
        "bot_id": BOT_ID,
        "bot_name": BOT_NAME,
        "asset_class": ASSET_CLASS,
        "timeframe": "1h",
        "status": status,
        "updated_at": utc_now(),
        "total_return_pct": metrics["total_return_pct"],
        "sharpe_ratio": headline.get("research_sharpe", metrics["sharpe_ratio"]),
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "win_rate_pct": metrics["win_rate_pct"],
        "profit_factor": metrics["profit_factor"],
        "trade_count": metrics["trade_count"],
        "current_position": current,
        "cash_usdt": metrics["cash_usdt"],
        "equity_usdt": metrics["equity_usdt"],
        "open_pnl_usdt": metrics["open_pnl_usdt"],
        "equity_curve": list(account.get("equity_curve") or [])[-500:],
        "recent_trades": list(account.get("trades") or [])[-20:][::-1],
        "accepted": bool(headline.get("accepted", True)),
        "acceptance_note": headline.get("acceptance_note"),
        "gates_passed": headline.get("gates_passed"),
        "gates_total": headline.get("gates_total"),
        "research_return_pct": headline.get("research_return_pct"),
        "research_sharpe_ratio": headline.get("research_sharpe_ratio"),
        "research_max_drawdown_pct": headline.get("research_max_drawdown_pct"),
        "research_win_rate_pct": headline.get("research_win_rate_pct"),
        "research_profit_factor": headline.get("research_profit_factor"),
        "research_trade_count": headline.get("research_trade_count"),
        "data_source": "Yahoo Finance GC=F 1h (live paper)",
        "mode": "paper_live",
        "logs": list(account.get("logs") or [])[-40:],
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def _close_lot(
    account: dict[str, Any],
    *,
    exit_px: float,
    ts: pd.Timestamp,
    reason: str,
) -> None:
    lot = account.get("position")
    if not lot:
        return
    qty = float(lot["qty"])
    side = lot["side"]
    fill_side = "sell" if side == "long" else "buy"
    fill_px = gold_fill_price(exit_px, fill_side)
    pnl = (fill_px - float(lot["entry"])) * qty * (1 if side == "long" else -1)
    pnl -= _apply_cost(qty, fill_px)
    account["cash"] = float(account["cash"]) + pnl
    trades = list(account.get("trades") or [])
    trades.append({
        "symbol": "XAU/USD",
        "side": side,
        "entry_time": lot["entry_time"],
        "exit_time": str(ts),
        "entry_price": float(lot["entry"]),
        "exit_price": fill_px,
        "quantity": qty,
        "pnl_usdt": pnl,
        "reason": reason,
    })
    account["trades"] = trades[-200:]
    account["position"] = None
    append_log(account, f"EXIT {side} @ {fill_px:.2f} ({reason}) pnl={pnl:.2f}")
    try:
        from orbit.notify import GOLD_BOT, notify_paper_exit

        equity = float(account["cash"])
        notify_paper_exit(
            GOLD_BOT,
            side=side,
            symbol="XAU/USD",
            qty=qty,
            price=fill_px,
            pnl=pnl,
            reason=reason,
            equity=equity,
        )
    except Exception:
        pass


def _process_bar(account: dict[str, Any], row: dict[str, Any], rules: gold_strategy.GoldRules) -> None:
    ts = _as_ts(row["timestamp"])
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    atr_raw = row.get("atr")
    atr = float(atr_raw) if atr_raw is not None and pd.notna(atr_raw) else float("nan")
    lot = account.get("position")

    if lot is not None and pd.notna(atr):
        side = lot["side"]
        extreme = float(lot["extreme"])
        stop = float(lot["stop"])
        if side == "long":
            extreme = max(extreme, high)
            hit = low <= stop
            exit_px = stop if hit else None
        else:
            extreme = min(extreme, low)
            hit = high >= stop
            exit_px = stop if hit else None
        timed = gold_strategy.hours_held(_as_ts(lot["entry_time"]), ts) >= rules.time_stop_hours
        reason = ""
        if timed and exit_px is None:
            exit_px, hit, reason = close, True, "time_stop"
        elif hit:
            reason = "stop"
        if hit and exit_px is not None:
            _close_lot(account, exit_px=float(exit_px), ts=ts, reason=reason)
        else:
            lot["extreme"] = extreme
            lot["stop"] = gold_strategy.update_stop(
                side, float(lot["entry"]), stop, extreme, float(atr), rules=rules
            )
            lot["bars_held"] = int(lot.get("bars_held") or 0) + 1
            account["position"] = lot

    if account.get("position") is None:
        signal = gold_strategy.evaluate_entry(row, rules)
        if signal is not None:
            qty = gold_strategy.position_size(float(account["cash"]), signal.entry, signal.stop, rules)
            if qty > 0:
                fill_side = "buy" if signal.side == "long" else "sell"
                fill_px = gold_fill_price(signal.entry, fill_side)
                delta = fill_px - signal.entry
                account["cash"] = float(account["cash"]) - _apply_cost(qty, fill_px)
                account["position"] = {
                    "side": signal.side,
                    "entry": fill_px,
                    "stop": signal.stop + delta,
                    "qty": qty,
                    "entry_time": str(ts),
                    "atr": signal.atr,
                    "extreme": fill_px,
                    "bars_held": 0,
                }
                append_log(
                    account,
                    f"ENTRY {signal.side} @ {fill_px:.2f} qty={qty:.4f} stop={signal.stop + delta:.2f}",
                )
                try:
                    from orbit.notify import GOLD_BOT, notify_paper_entry

                    notify_paper_entry(
                        GOLD_BOT,
                        side=signal.side,
                        symbol="XAU/USD",
                        qty=qty,
                        price=fill_px,
                        stop=signal.stop + delta,
                        equity=_mark(account, close),
                    )
                except Exception:
                    pass

    equity = _mark(account, close)
    append_equity(account, equity, str(ts))
    account["last_processed_bar_ts"] = str(ts)


def run_iteration(*, force_refresh: bool = False) -> dict[str, Any]:
    account = _load()
    settings = gold_settings.load_settings()
    rules = gold_settings.rules_from_settings(settings)
    if not account.get("enabled", True) or not settings.get("bot_enabled", False):
        account["bot_running"] = False
        save_account(ACCOUNT_PATH, account)
        return export_live_state(account)

    try:
        # Prefer cache; refresh when asked (loop does this periodically).
        frame = fetch_gold_hourly(force=force_refresh)
    except Exception as exc:  # noqa: BLE001
        append_log(account, f"Yahoo fetch failed: {exc}", "ERROR")
        save_account(ACCOUNT_PATH, account)
        return export_live_state(account)

    frame = frame.tail(LIVE_TAIL).reset_index(drop=True)
    data = gold_strategy.add_indicators(frame, rules)
    last_ts = account.get("last_processed_bar_ts")
    if last_ts is None and len(data) > WARMUP_BARS:
        # First run: warm up on recent history only (RAM-safe).
        start_ts = str(data.iloc[-WARMUP_BARS]["timestamp"])
        account["last_processed_bar_ts"] = start_ts
        last_ts = start_ts
        append_log(account, f"Warm-start from {start_ts}")

    cols = list(data.columns)
    processed = 0
    for tup in data.itertuples(index=False, name=None):
        row = dict(zip(cols, tup))
        ts = str(_as_ts(row["timestamp"]))
        if last_ts is not None and ts <= str(_as_ts(last_ts)):
            continue
        _process_bar(account, row, rules)
        processed += 1

    if processed == 0 and len(data):
        # Mark-to-market on latest close even when no new bar.
        close = float(data.iloc[-1]["close"])
        append_equity(account, _mark(account, close), str(data.iloc[-1]["timestamp"]))

    account["bot_running"] = True
    append_log(account, f"Cycle ok — processed {processed} new bar(s)")
    save_account(ACCOUNT_PATH, account)
    try:
        from orbit.notify import maybe_notify_daily_desk

        maybe_notify_daily_desk()
    except Exception:
        pass
    return export_live_state(account)


def run_bot_loop(stop_event: threading.Event) -> None:
    # Keep settings.bot_enabled in sync — run_iteration gates on it, and
    # ORBIT_AUTOSTART used to start the thread with bot_enabled still false.
    gold_settings.save_settings({"bot_enabled": True})
    account = _load()
    account["enabled"] = True
    account["bot_running"] = True
    append_log(account, "Gold paper bot started (Yahoo GC=F test money)")
    save_account(ACCOUNT_PATH, account)
    export_live_state(account)

    cycles = 0
    while not stop_event.is_set():
        force = cycles == 0 or cycles % 10 == 0
        try:
            run_iteration(force_refresh=force)
        except Exception as exc:  # noqa: BLE001
            account = _load()
            append_log(account, f"Cycle error: {exc}", "ERROR")
            save_account(ACCOUNT_PATH, account)
            export_live_state(account)
        cycles += 1
        interval = int(gold_settings.load_settings().get("loop_interval_sec") or LOOP_INTERVAL_SEC)
        stop_event.wait(interval)

    account = _load()
    account["bot_running"] = False
    append_log(account, "Gold paper bot stopped")
    save_account(ACCOUNT_PATH, account)
    export_live_state(account)


def set_enabled(enabled: bool) -> dict[str, Any]:
    enabled = bool(enabled)
    gold_settings.save_settings({"bot_enabled": enabled})
    account = _load()
    was = bool(account.get("enabled", True))
    account["enabled"] = enabled
    if was != enabled:
        append_log(account, "Trading enabled" if enabled else "Trading paused")
    save_account(ACCOUNT_PATH, account)
    return export_live_state(account)


def flatten_now(*, reason: str = "manual_flatten") -> dict[str, Any]:
    """Close the open paper lot at the latest mark (if any)."""
    account = _load()
    lot = account.get("position")
    if not lot:
        append_log(account, "Flatten requested — already flat")
        save_account(ACCOUNT_PATH, account)
        return {"closed": None, "state": export_live_state(account)}
    try:
        frame = fetch_gold_hourly(force=True)
        close = float(frame.iloc[-1]["close"])
        ts = _as_ts(frame.iloc[-1]["timestamp"])
    except Exception as exc:  # noqa: BLE001
        close = float(lot.get("entry") or 0.0)
        ts = pd.Timestamp.now(tz="UTC")
        if close <= 0:
            return {"closed": None, "error": str(exc), "state": export_live_state(account)}
    side = str(lot.get("side") or "long")
    qty = float(lot.get("qty") or 0.0)
    _close_lot(account, exit_px=close, ts=ts, reason=reason)
    append_log(account, f"Manual flatten closed {side} qty={qty:.6g} @ {close:.2f}")
    save_account(ACCOUNT_PATH, account)
    return {
        "closed": {"side": side, "qty": qty, "price": close, "reason": reason},
        "state": export_live_state(account),
    }
