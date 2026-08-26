"""MNQ 15m Opening Range Breakout engine and dashboard state exporter."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import strategy as mnq_strategy
from .data import fetch_mnq_15m

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "mnq_state.json"
WF_PATH = ROOT / "backtest_output" / "walk_forward_mnq.json"

BOT_NAME = "Nasdaq 15m ORB"
BOT_ID = "mnq"
ASSET_CLASS = "MNQ Futures"


@dataclass
class _Lot:
    side: str
    entry: float
    stop: float
    take_profit: float
    qty: float
    entry_time: pd.Timestamp


@dataclass
class MnqResult:
    initial_capital: float
    final_equity: float
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    bars: int = 0


def _as_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def run_backtest(
    frame: pd.DataFrame | None = None,
    *,
    initial_capital: float = 1_000.0,
    point_value: float = 2.0,
    commission_per_contract: float = 0.50,
    rules: mnq_strategy.MnqRules | None = None,
) -> MnqResult:
    rules = rules or mnq_strategy.MnqRules()
    raw = frame if frame is not None else fetch_mnq_15m()
    data = mnq_strategy.add_indicators(raw, rules)
    cash = initial_capital
    lot: _Lot | None = None
    or_high: float | None = None
    or_low: float | None = None
    trades_today = 0
    current_day: str | None = None
    result = MnqResult(initial_capital=initial_capital, final_equity=initial_capital)

    def mark(price: float) -> float:
        if lot is None:
            return cash
        pnl = (price - lot.entry) * lot.qty * point_value * (1 if lot.side == "long" else -1)
        return cash + pnl

    cols = list(data.columns)
    for tup in data.itertuples(index=False, name=None):
        mapping = dict(zip(cols, tup))
        ts = _as_ts(mapping["timestamp"])
        day = str(mapping["cet_date"])
        if day != current_day:
            current_day = day
            trades_today = 0
            or_high = None
            or_low = None
            if lot is not None:
                px = float(mapping["open"])
                pnl = (px - lot.entry) * lot.qty * point_value * (1 if lot.side == "long" else -1)
                pnl -= commission_per_contract * lot.qty
                cash += pnl
                result.trades.append({
                    "symbol": "MNQ",
                    "side": lot.side,
                    "entry_time": str(lot.entry_time),
                    "exit_time": str(ts),
                    "entry_price": lot.entry,
                    "exit_price": px,
                    "quantity": lot.qty,
                    "pnl_usdt": pnl,
                    "reason": "session_reset",
                })
                lot = None

        if mnq_strategy.is_opening_range_bar(mapping, rules):
            bar_high = float(mapping["high"])
            bar_low = float(mapping["low"])
            or_high = bar_high if or_high is None else max(or_high, bar_high)
            or_low = bar_low if or_low is None else min(or_low, bar_low)

        high = float(mapping["high"])
        low = float(mapping["low"])
        close = float(mapping["close"])
        result.bars += 1

        if lot is not None:
            exit_px = None
            reason = ""
            if lot.side == "long":
                if low <= lot.stop:
                    exit_px, reason = lot.stop, "stop"
                elif high >= lot.take_profit:
                    exit_px, reason = lot.take_profit, "take_profit"
            else:
                if high >= lot.stop:
                    exit_px, reason = lot.stop, "stop"
                elif low <= lot.take_profit:
                    exit_px, reason = lot.take_profit, "take_profit"
            if exit_px is None and mnq_strategy.should_force_flat(mapping, rules):
                exit_px, reason = close, "eod_flat"
            if exit_px is not None:
                pnl = (exit_px - lot.entry) * lot.qty * point_value * (
                    1 if lot.side == "long" else -1
                )
                pnl -= commission_per_contract * lot.qty
                cash += pnl
                result.trades.append({
                    "symbol": "MNQ",
                    "side": lot.side,
                    "entry_time": str(lot.entry_time),
                    "exit_time": str(ts),
                    "entry_price": lot.entry,
                    "exit_price": exit_px,
                    "quantity": lot.qty,
                    "pnl_usdt": pnl,
                    "reason": reason,
                })
                lot = None

        if lot is None:
            signal = mnq_strategy.evaluate_entry(
                mapping,
                or_high=or_high,
                or_low=or_low,
                trades_today=trades_today,
                rules=rules,
            )
            if signal is not None:
                risk_pts = abs(signal.entry - signal.stop)
                qty, _forced = mnq_strategy.size_contracts(
                    cash, risk_pts, point_value=point_value
                )
                if qty >= 1:
                    cash -= commission_per_contract * qty
                    lot = _Lot(
                        side=signal.side,
                        entry=signal.entry,
                        stop=signal.stop,
                        take_profit=signal.take_profit,
                        qty=qty,
                        entry_time=ts,
                    )
                    trades_today += 1

        result.equity_curve.append({"timestamp": str(ts), "equity": mark(close)})

    if lot is not None:
        last = data.iloc[-1]
        px = float(last["close"])
        pnl = (px - lot.entry) * lot.qty * point_value * (1 if lot.side == "long" else -1)
        pnl -= commission_per_contract * lot.qty
        cash += pnl
        result.trades.append({
            "symbol": "MNQ",
            "side": lot.side,
            "entry_time": str(lot.entry_time),
            "exit_time": str(last["timestamp"]),
            "entry_price": lot.entry,
            "exit_price": px,
            "quantity": lot.qty,
            "pnl_usdt": pnl,
            "reason": "end_of_test",
        })
        result.equity_curve[-1]["equity"] = cash

    result.final_equity = cash
    return result


def metrics_from_result(result: MnqResult) -> dict[str, float]:
    curve = pd.DataFrame(result.equity_curve)
    if curve.empty:
        return {
            "total_return_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "trade_count": 0,
            "expectancy_usdt": 0.0,
            "gross_profit_usdt": 0.0,
            "gross_loss_usdt": 0.0,
        }
    curve["timestamp"] = pd.to_datetime(curve["timestamp"], utc=True)
    equity = curve["equity"].astype(float)
    daily = curve.set_index("timestamp")["equity"].resample("1D").last().dropna()
    rets = daily.pct_change().dropna()
    total = float(equity.iloc[-1] / result.initial_capital - 1.0) * 100
    vol = float(rets.std(ddof=0)) or 1e-12
    sharpe = float(rets.mean() / vol * np.sqrt(252)) if not rets.empty else 0.0
    dd = float((equity / equity.cummax() - 1.0).min() * 100)
    pnls = [float(t["pnl_usdt"]) for t in result.trades]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    return {
        "total_return_pct": round(total, 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown_pct": round(dd, 2),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
        "profit_factor": round(sum(wins) / sum(losses), 2) if losses else (10.0 if wins else 0.0),
        "trade_count": len(pnls),
        "expectancy_usdt": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "gross_profit_usdt": round(sum(wins), 2),
        "gross_loss_usdt": round(sum(losses), 2),
    }


def _headline_from_walk_forward() -> dict[str, Any] | None:
    if not WF_PATH.exists():
        return None
    try:
        payload = json.loads(WF_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    agg = payload.get("aggregate") or {}
    if not agg:
        return None
    return {
        "total_return_pct": round(float(agg.get("return_pct") or 0.0), 2),
        "sharpe_ratio": round(float(agg.get("sharpe") or 0.0), 2),
        "max_drawdown_pct": round(float(agg.get("max_drawdown_pct") or 0.0), 2),
        "win_rate_pct": round(float(agg.get("win_rate_pct") or 0.0), 1),
        "profit_factor": round(float(agg.get("profit_factor") or 0.0), 2),
        "trade_count": int(agg.get("trade_count") or 0),
        "accepted": bool(payload.get("accepted")),
        "equity_curve": payload.get("oos_curve") or [],
    }


def export_state(
    result: MnqResult | None = None,
    *,
    status: str = "PAPER",
    path: Path | None = None,
    rules: mnq_strategy.MnqRules | None = None,
) -> dict[str, Any]:
    result = result or run_backtest(rules=rules)
    metrics = metrics_from_result(result)
    headline = _headline_from_walk_forward()
    if headline:
        metrics.update({
            "total_return_pct": headline["total_return_pct"],
            "sharpe_ratio": headline["sharpe_ratio"],
            "max_drawdown_pct": headline["max_drawdown_pct"],
            "win_rate_pct": headline["win_rate_pct"] or metrics["win_rate_pct"],
            "profit_factor": headline["profit_factor"] or metrics["profit_factor"],
            "trade_count": headline["trade_count"] or metrics["trade_count"],
        })
    payload = {
        "bot_id": BOT_ID,
        "bot_name": BOT_NAME,
        "asset_class": ASSET_CLASS,
        "timeframe": "15m",
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_return_pct": metrics["total_return_pct"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "win_rate_pct": metrics["win_rate_pct"],
        "profit_factor": metrics["profit_factor"],
        "trade_count": metrics["trade_count"],
        "current_position": None,
        "equity_usdt": result.final_equity,
        "equity_curve": result.equity_curve[-500:],
        "recent_trades": result.trades[-20:][::-1],
        "accepted": bool(headline["accepted"]) if headline else metrics["total_return_pct"] > 0 and metrics["sharpe_ratio"] > 0,
        "data_source": "Yahoo Finance MNQ=F 15m",
        "logs": [
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "message": (
                    f"MNQ ORB exported {metrics['trade_count']} trades "
                    f"from real MNQ=F 15m data"
                ),
            }
        ],
    }
    target = path or STATE_PATH
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> None:
    result = run_backtest()
    payload = export_state(result, status="PAPER")
    print(f"{BOT_NAME}: return={payload['total_return_pct']}% trades={payload['trade_count']}")
    print(f"Wrote {STATE_PATH}")


if __name__ == "__main__":
    main()
