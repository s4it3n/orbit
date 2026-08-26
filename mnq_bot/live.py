"""MNQ live paper loop — test money marked to Yahoo MNQ/NQ/QQQ."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pandas as pd

from paper import append_equity, append_log, load_account, metrics_from_account, save_account, utc_now
from paper.loops import is_running as loop_running

from . import strategy as mnq_strategy
from .data import fetch_mnq_15m

ROOT = Path(__file__).resolve().parent.parent
ACCOUNT_PATH = ROOT / "mnq_live.json"
STATE_PATH = ROOT / "mnq_state.json"
WF_PATH = ROOT / "backtest_output" / "walk_forward_mnq.json"

BOT_ID = "mnq"
BOT_NAME = "Nasdaq 15m ORB"
ASSET_CLASS = "MNQ Futures"
INITIAL_CAPITAL = float(os.getenv("MNQ_PAPER_EQUITY", os.getenv("ORBIT_PAPER_EQUITY", "1000")))
POINT_VALUE = 2.0
COMMISSION = 0.50
LOOP_INTERVAL_SEC = 90
WARMUP_BARS = 260
LIVE_TAIL = 400

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
    "or_high": None,
    "or_low": None,
    "trades_today": 0,
    "current_day": None,
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
        "or_high": None,
        "or_low": None,
        "trades_today": 0,
        "current_day": None,
    }


def _ensure_paper_capital(account: dict[str, Any]) -> dict[str, Any]:
    stored = float(account.get("initial_capital") or 0.0)
    if abs(stored - INITIAL_CAPITAL) < 1e-9:
        return account
    reset = _fresh_defaults(
        enabled=bool(account.get("enabled", True)),
        bot_running=bool(account.get("bot_running", False)),
    )
    append_log(reset, f"Reset paper account to ${INITIAL_CAPITAL:.0f}")
    return reset


def _load() -> dict[str, Any]:
    return _ensure_paper_capital(load_account(ACCOUNT_PATH, _DEFAULTS))


def _as_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _mark(account: dict[str, Any], price: float) -> float:
    cash = float(account["cash"])
    lot = account.get("position")
    if not lot:
        return cash
    side = 1 if lot["side"] == "long" else -1
    return cash + (price - float(lot["entry"])) * float(lot["qty"]) * POINT_VALUE * side


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
    return {
        "research_sharpe": round(float(agg.get("sharpe") or 0.0), 2),
        "research_return_pct": round(float(agg.get("return_pct") or 0.0), 2),
        "accepted": bool(payload.get("accepted")),
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
            "symbol": "MNQ",
            "side": lot["side"],
            "entry_price": lot["entry"],
            "stop": lot["stop"],
            "take_profit": lot["take_profit"],
            "quantity": lot["qty"],
            "entry_time": lot["entry_time"],
        }
    headline = _headline() or {}
    payload = {
        "bot_id": BOT_ID,
        "bot_name": BOT_NAME,
        "asset_class": ASSET_CLASS,
        "timeframe": "15m",
        "status": status,
        "updated_at": utc_now(),
        "total_return_pct": metrics["total_return_pct"],
        "sharpe_ratio": headline.get("research_sharpe", metrics["sharpe_ratio"]),
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "win_rate_pct": metrics["win_rate_pct"],
        "profit_factor": metrics["profit_factor"],
        "trade_count": metrics["trade_count"],
        "current_position": current,
        "equity_usdt": metrics["equity_usdt"],
        "equity_curve": list(account.get("equity_curve") or [])[-500:],
        "recent_trades": list(account.get("trades") or [])[-20:][::-1],
        "accepted": bool(headline.get("accepted", True)),
        "research_return_pct": headline.get("research_return_pct"),
        "data_source": "Yahoo Finance MNQ/NQ/QQQ 15m (live paper)",
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
    pnl = (exit_px - float(lot["entry"])) * qty * POINT_VALUE * (1 if side == "long" else -1)
    pnl -= COMMISSION * qty
    account["cash"] = float(account["cash"]) + pnl
    trades = list(account.get("trades") or [])
    trades.append({
        "symbol": "MNQ",
        "side": side,
        "entry_time": lot["entry_time"],
        "exit_time": str(ts),
        "entry_price": float(lot["entry"]),
        "exit_price": exit_px,
        "quantity": qty,
        "pnl_usdt": pnl,
        "reason": reason,
    })
    account["trades"] = trades[-200:]
    account["position"] = None
    append_log(account, f"EXIT {side} @ {exit_px:.2f} ({reason}) pnl={pnl:.2f}")
    try:
        from orbit.notify import MNQ_BOT, notify_paper_exit

        notify_paper_exit(
            MNQ_BOT,
            side=side,
            symbol="MNQ",
            qty=qty,
            price=exit_px,
            pnl=pnl,
            reason=reason,
            equity=float(account["cash"]),
        )
    except Exception:
        pass


def _process_bar(account: dict[str, Any], row: dict[str, Any], rules: mnq_strategy.MnqRules) -> None:
    ts = _as_ts(row["timestamp"])
    day = str(row["cet_date"])
    if day != account.get("current_day"):
        account["current_day"] = day
        account["trades_today"] = 0
        account["or_high"] = None
        account["or_low"] = None
        if account.get("position") is not None:
            _close_lot(account, exit_px=float(row["open"]), ts=ts, reason="session_reset")

    if mnq_strategy.is_opening_range_bar(row, rules):
        bar_high = float(row["high"])
        bar_low = float(row["low"])
        or_high = account.get("or_high")
        or_low = account.get("or_low")
        account["or_high"] = bar_high if or_high is None else max(float(or_high), bar_high)
        account["or_low"] = bar_low if or_low is None else min(float(or_low), bar_low)

    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    lot = account.get("position")

    if lot is not None:
        exit_px = None
        reason = ""
        if lot["side"] == "long":
            if low <= float(lot["stop"]):
                exit_px, reason = float(lot["stop"]), "stop"
            elif high >= float(lot["take_profit"]):
                exit_px, reason = float(lot["take_profit"]), "take_profit"
        else:
            if high >= float(lot["stop"]):
                exit_px, reason = float(lot["stop"]), "stop"
            elif low <= float(lot["take_profit"]):
                exit_px, reason = float(lot["take_profit"]), "take_profit"
        if exit_px is None and mnq_strategy.should_force_flat(row, rules):
            exit_px, reason = close, "eod_flat"
        if exit_px is not None:
            _close_lot(account, exit_px=float(exit_px), ts=ts, reason=reason)

    if account.get("position") is None:
        signal = mnq_strategy.evaluate_entry(
            row,
            or_high=account.get("or_high"),
            or_low=account.get("or_low"),
            trades_today=int(account.get("trades_today") or 0),
            rules=rules,
        )
        if signal is not None:
            risk_pts = abs(signal.entry - signal.stop)
            qty, forced = mnq_strategy.size_contracts(
                float(account["cash"]), risk_pts, point_value=POINT_VALUE
            )
            if qty >= 1:
                account["cash"] = float(account["cash"]) - COMMISSION * qty
                account["position"] = {
                    "side": signal.side,
                    "entry": signal.entry,
                    "stop": signal.stop,
                    "take_profit": signal.take_profit,
                    "qty": qty,
                    "entry_time": str(ts),
                }
                account["trades_today"] = int(account.get("trades_today") or 0) + 1
                note = " (forced 1-lot for $1k paper)" if forced else ""
                if forced:
                    append_log(
                        account,
                        f"Forced MNQ qty=1 — 1-lot risk "
                        f"{risk_pts * POINT_VALUE:.2f} ≤ 2% of cash",
                    )
                append_log(
                    account,
                    f"ENTRY {signal.side} @ {signal.entry:.2f} qty={qty} "
                    f"stop={signal.stop:.2f} tp={signal.take_profit:.2f}{note}",
                )
                try:
                    from orbit.notify import MNQ_BOT, notify_paper_entry

                    notify_paper_entry(
                        MNQ_BOT,
                        side=signal.side,
                        symbol="MNQ",
                        qty=float(qty),
                        price=signal.entry,
                        stop=signal.stop,
                        equity=_mark(account, close),
                    )
                except Exception:
                    pass

    append_equity(account, _mark(account, close), str(ts))
    account["last_processed_bar_ts"] = str(ts)


def run_iteration(*, force_refresh: bool = False) -> dict[str, Any]:
    account = _load()
    rules = mnq_strategy.MnqRules()
    if not account.get("enabled", True):
        account["bot_running"] = False
        save_account(ACCOUNT_PATH, account)
        return export_live_state(account)

    try:
        frame = fetch_mnq_15m(force=force_refresh)
    except Exception as exc:  # noqa: BLE001
        append_log(account, f"Yahoo fetch failed: {exc}", "ERROR")
        save_account(ACCOUNT_PATH, account)
        return export_live_state(account)

    frame = frame.tail(LIVE_TAIL).reset_index(drop=True)
    data = mnq_strategy.add_indicators(frame, rules)
    last_ts = account.get("last_processed_bar_ts")
    if last_ts is None and len(data) > WARMUP_BARS:
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
        close = float(data.iloc[-1]["close"])
        append_equity(account, _mark(account, close), str(data.iloc[-1]["timestamp"]))

    account["bot_running"] = True
    append_log(account, f"Cycle ok — processed {processed} new bar(s)")
    save_account(ACCOUNT_PATH, account)
    return export_live_state(account)


def run_bot_loop(stop_event: threading.Event) -> None:
    account = _load()
    account["enabled"] = True
    account["bot_running"] = True
    append_log(account, "MNQ paper bot started (Yahoo test money)")
    save_account(ACCOUNT_PATH, account)
    export_live_state(account)

    cycles = 0
    while not stop_event.is_set():
        force = cycles == 0 or cycles % 8 == 0
        try:
            run_iteration(force_refresh=force)
        except Exception as exc:  # noqa: BLE001
            account = _load()
            append_log(account, f"Cycle error: {exc}", "ERROR")
            save_account(ACCOUNT_PATH, account)
            export_live_state(account)
        cycles += 1
        stop_event.wait(LOOP_INTERVAL_SEC)

    account = _load()
    account["bot_running"] = False
    append_log(account, "MNQ paper bot stopped")
    save_account(ACCOUNT_PATH, account)
    export_live_state(account)


def set_enabled(enabled: bool) -> dict[str, Any]:
    account = _load()
    account["enabled"] = bool(enabled)
    append_log(account, "Trading enabled" if enabled else "Trading paused")
    save_account(ACCOUNT_PATH, account)
    return export_live_state(account)
