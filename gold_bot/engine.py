"""Gold 1H paper/backtest engine and dashboard state exporter."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import strategy as gold_strategy
from .data import fetch_gold_hourly

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "gold_state.json"
WF_PATH = ROOT / "backtest_output" / "walk_forward_gold.json"

BOT_NAME = "Gold 1H Volatility Breakout"
BOT_ID = "gold"
ASSET_CLASS = "XAU/USD"


@dataclass
class _Lot:
    side: str
    entry: float
    stop: float
    qty: float
    entry_time: pd.Timestamp
    atr: float
    extreme: float
    bars_held: int = 0


@dataclass
class GoldResult:
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
    initial_capital: float = 100_000.0,
    rules: gold_strategy.GoldRules | None = None,
    cost_bps: float = 0.5,
) -> GoldResult:
    """Backtest the Donchian squeeze breakout on hourly gold futures.

    ``cost_bps`` is one-way transaction cost in basis points of notional.
    """
    rules = rules or gold_strategy.GoldRules()
    raw = frame if frame is not None else fetch_gold_hourly()
    data = gold_strategy.add_indicators(raw, rules)
    cash = initial_capital
    lot: _Lot | None = None
    result = GoldResult(initial_capital=initial_capital, final_equity=initial_capital)

    def mark(price: float) -> float:
        if lot is None:
            return cash
        pnl = (price - lot.entry) * lot.qty * (1 if lot.side == "long" else -1)
        return cash + pnl

    def apply_cost(qty: float, price: float) -> float:
        return abs(qty) * price * cost_bps / 10_000.0

    cols = list(data.columns)
    for tup in data.itertuples(index=False, name=None):
        row = dict(zip(cols, tup))
        ts = _as_ts(row["timestamp"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        atr = float(row["atr"]) if pd.notna(row["atr"]) else float("nan")
        result.bars += 1

        if lot is not None and np.isfinite(atr):
            if lot.side == "long":
                lot.extreme = max(lot.extreme, high)
                hit = low <= lot.stop
                exit_px = lot.stop if hit else None
            else:
                lot.extreme = min(lot.extreme, low)
                hit = high >= lot.stop
                exit_px = lot.stop if hit else None
            timed = gold_strategy.hours_held(lot.entry_time, ts) >= rules.time_stop_hours
            if timed and exit_px is None:
                exit_px = close
                hit = True
                reason = "time_stop"
            elif hit:
                reason = "stop"
            else:
                reason = ""
            if hit and exit_px is not None:
                pnl = (exit_px - lot.entry) * lot.qty * (1 if lot.side == "long" else -1)
                pnl -= apply_cost(lot.qty, exit_px)
                cash += pnl
                result.trades.append({
                    "symbol": "XAU/USD",
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
            else:
                lot.stop = gold_strategy.update_stop(
                    lot.side, lot.entry, lot.stop, lot.extreme, atr, rules=rules
                )
                lot.bars_held += 1

        if lot is None:
            signal = gold_strategy.evaluate_entry(row, rules)
            if signal is not None:
                qty = gold_strategy.position_size(cash, signal.entry, signal.stop, rules)
                if qty > 0:
                    cash -= apply_cost(qty, signal.entry)
                    lot = _Lot(
                        side=signal.side,
                        entry=signal.entry,
                        stop=signal.stop,
                        qty=qty,
                        entry_time=ts,
                        atr=signal.atr,
                        extreme=signal.entry,
                    )

        result.equity_curve.append({"timestamp": str(ts), "equity": mark(close)})

    if lot is not None:
        last = data.iloc[-1]
        px = float(last["close"])
        pnl = (px - lot.entry) * lot.qty * (1 if lot.side == "long" else -1)
        pnl -= apply_cost(lot.qty, px)
        cash += pnl
        result.trades.append({
            "symbol": "XAU/USD",
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


def metrics_from_result(result: GoldResult) -> dict[str, float]:
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
    result: GoldResult | None = None,
    *,
    status: str = "PAPER",
    path: Path | None = None,
    rules: gold_strategy.GoldRules | None = None,
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
        "timeframe": "1h",
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
        "data_source": "Yahoo Finance GC=F 1h",
        "logs": [
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "message": (
                    f"Gold engine exported {metrics['trade_count']} trades "
                    f"from real GC=F hourly data"
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
