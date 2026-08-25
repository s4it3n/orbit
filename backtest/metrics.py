"""Performance metrics for rotation backtests."""

from __future__ import annotations

import math
from typing import Any, Sequence

import pandas as pd

from orbit import data

from .config import BacktestConfig
from .engine import BacktestResult

DAYS_PER_YEAR = 365.25


def equity_stats(curve: Sequence[dict]) -> dict[str, float]:
    """Risk and return statistics for any equity curve.

    Shared by the strategy and every benchmark so the comparison is like for like.
    """
    frame = pd.DataFrame(list(curve))
    if frame.empty:
        raise ValueError("Cannot calculate metrics for an empty equity curve.")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    equity = frame["equity"].astype(float)
    returns = equity.pct_change().dropna()

    elapsed_days = max(
        (frame["timestamp"].iloc[-1] - frame["timestamp"].iloc[0]).total_seconds()
        / 86400,
        1.0,
    )
    periods_per_year = len(frame) / elapsed_days * DAYS_PER_YEAR
    years = elapsed_days / DAYS_PER_YEAR

    volatility = float(returns.std(ddof=0))
    downside = float(returns[returns < 0].std(ddof=0)) if (returns < 0).any() else 0.0
    mean_return = float(returns.mean()) if not returns.empty else 0.0
    sharpe = (
        mean_return / volatility * math.sqrt(periods_per_year) if volatility else 0.0
    )
    sortino = (
        mean_return / downside * math.sqrt(periods_per_year) if downside else 0.0
    )

    running_peak = equity.cummax()
    max_drawdown = float(((equity / running_peak) - 1).min())

    start = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    total_return = final / start - 1 if start > 0 else 0.0
    cagr = (
        (final / start) ** (1 / years) - 1
        if years > 0 and final > 0 and start > 0
        else 0.0
    )
    return {
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "calmar": cagr / abs(max_drawdown) if max_drawdown else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "annual_volatility_pct": volatility * math.sqrt(periods_per_year) * 100,
        "years": years,
    }


def _per_symbol(trades: Sequence[dict]) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = {}
    for trade in trades:
        symbol = str(trade.get("symbol") or "?")
        row = grouped.setdefault(
            symbol, {"symbol": symbol, "trades": 0, "wins": 0, "pnl_usdt": 0.0}
        )
        row["trades"] += 1
        pnl = float(trade["pnl_usdt"])
        row["pnl_usdt"] += pnl
        if pnl > 0:
            row["wins"] += 1
    rows = []
    for row in grouped.values():
        rows.append({
            "symbol": row["symbol"],
            "trades": row["trades"],
            "pnl_usdt": round(row["pnl_usdt"], 2),
            "win_rate_pct": round(row["wins"] / row["trades"] * 100, 1),
        })
    rows.sort(key=lambda item: item["pnl_usdt"], reverse=True)
    return rows


def calculate_metrics(
    result: BacktestResult,
    panel: "data.Panel | None" = None,
    cfg: BacktestConfig | None = None,
) -> dict:
    """Full metric set. Benchmarks are included when a *panel* is supplied."""
    stats = equity_stats(result.equity_curve)
    years = stats.pop("years")

    pnl = [float(trade["pnl_usdt"]) for trade in result.trades]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    holds = [float(trade.get("bars_held") or 0) for trade in result.trades]

    metrics: dict[str, Any] = {
        "initial_capital": result.initial_capital,
        "final_equity": result.final_equity,
        "trade_count": len(pnl),
        "win_rate_pct": len(wins) / len(pnl) * 100 if pnl else 0.0,
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss
            else (math.inf if wins else 0.0)
        ),
        "expectancy_usdt": sum(pnl) / len(pnl) if pnl else 0.0,
        "gross_profit_usdt": gross_profit,
        "gross_loss_usdt": gross_loss,
        "fees_paid_usdt": result.fees_paid,
        "rotations": result.rotations,
        "exposure_pct": (
            (result.bars - result.cash_bars) / result.bars * 100
            if result.bars
            else 0.0
        ),
        "cash_time_pct": (
            result.cash_bars / result.bars * 100 if result.bars else 0.0
        ),
        "avg_hold_days": sum(holds) / len(holds) if holds else 0.0,
        "trades_per_year": len(pnl) / years if years > 0 else 0.0,
        "per_symbol": _per_symbol(result.trades),
        "skipped_signals": result.skipped_signals,
        **stats,
    }

    if panel is not None and cfg is not None:
        from .benchmarks import buy_and_hold, equal_weight_basket

        btc = buy_and_hold(panel, cfg.regime_symbol, cfg.initial_capital, cfg.fee_rate)
        basket = equal_weight_basket(
            panel, cfg.universe, cfg.initial_capital, cfg.fee_rate
        )
        metrics.update({
            "benchmark_symbol": cfg.regime_symbol,
            "buy_hold_return_pct": btc["total_return_pct"],
            "buy_hold_max_drawdown_pct": btc["max_drawdown_pct"],
            "buy_hold_sharpe": btc["sharpe"],
            "buy_hold_cagr_pct": btc["cagr_pct"],
            "basket_return_pct": basket["total_return_pct"],
            "basket_max_drawdown_pct": basket["max_drawdown_pct"],
            "basket_sharpe": basket["sharpe"],
        })
    return metrics
