"""Backtest console and machine-readable reports."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .engine import BacktestResult

_ROWS = (
    ("initial_capital", "Initial capital"),
    ("final_equity", "Final equity"),
    ("total_return_pct", "Total return %"),
    ("buy_hold_return_pct", "BTC buy & hold %"),
    ("basket_return_pct", "Basket buy & hold %"),
    ("cagr_pct", "CAGR %"),
    ("max_drawdown_pct", "Max drawdown %"),
    ("buy_hold_max_drawdown_pct", "BTC max drawdown %"),
    ("sharpe", "Sharpe"),
    ("buy_hold_sharpe", "BTC Sharpe"),
    ("sortino", "Sortino"),
    ("calmar", "Calmar"),
    ("trade_count", "Trades"),
    ("trades_per_year", "Trades per year"),
    ("avg_hold_days", "Avg hold (days)"),
    ("win_rate_pct", "Win rate %"),
    ("profit_factor", "Profit factor"),
    ("expectancy_usdt", "Expectancy USDT"),
    ("fees_paid_usdt", "Fees paid USDT"),
    ("exposure_pct", "Exposure %"),
    ("cash_time_pct", "Time in cash %"),
    ("rotations", "Rotations"),
)


def print_report(metrics: dict) -> None:
    print("\nORBIT — DAILY MOMENTUM ROTATION")
    print("-" * 52)
    for key, label in _ROWS:
        if key not in metrics:
            continue
        value = metrics[key]
        if isinstance(value, float):
            print(f"{label:<26} {value:>14.4f}")
        else:
            print(f"{label:<26} {value:>14}")
    per_symbol = metrics.get("per_symbol") or []
    if per_symbol:
        print("-" * 52)
        print("PnL by asset")
        for row in per_symbol:
            print(
                f"  {row['symbol']:<12} trades={row['trades']:<4} "
                f"pnl={row['pnl_usdt']:>12.2f}  win={row['win_rate_pct']:>5.1f}%"
            )
    skipped = metrics.get("skipped_signals") or {}
    if skipped:
        print("-" * 52)
        print("Bars without an entry")
        for reason, count in sorted(
            skipped.items(), key=lambda item: item[1], reverse=True
        ):
            print(f"  {reason:<24} {count}")
    print("-" * 52)


def write_report(
    metrics: dict,
    result: BacktestResult,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_metrics = {
        key: ("Infinity" if value == float("inf") else value)
        for key, value in metrics.items()
    }
    (output_dir / "backtest_results.json").write_text(
        json.dumps(safe_metrics, indent=2, default=str),
        encoding="utf-8",
    )
    pd.DataFrame(result.trades).to_csv(output_dir / "trades.csv", index=False)
    pd.DataFrame(result.equity_curve).to_csv(
        output_dir / "equity_curve.csv", index=False
    )
