"""Rolling parameter selection with untouched out-of-sample test folds.

The acceptance gates below are fixed before any result is inspected, and the
benchmark is BTC buy-and-hold rather than zero: a long-only crypto strategy that
cannot beat simply holding BTC is not worth running.  Parameters are chosen on
each training window only; the following six months are scored once and never
used for selection.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from itertools import product

import pandas as pd

from orbit import data

from .benchmarks import buy_and_hold
from .config import BacktestConfig
from .engine import run_backtest
from .metrics import calculate_metrics, equity_stats

# Indicator-shaping parameters (each distinct pair needs its own panel).
MOMENTUM_GRID: tuple[tuple[int, ...], ...] = ((7, 14, 30), (10, 20, 40), (14, 30))
TREND_GRID: tuple[int, ...] = (150, 200)
# Selection-only parameters (reuse a panel, so they are cheap).
RANK_BUFFER_GRID: tuple[int, ...] = (2, 3)
MIN_HOLD_GRID: tuple[int, ...] = (5, 10)

TRAIN_MONTHS = 24
TEST_MONTHS = 6
STEP_MONTHS = 6
# 24 months of daily bars is roughly 730 rows; the old 1000-bar floor was an
# hourly-data assumption and would reject every fold.
MIN_TRAIN_BARS = 400
VALIDATION_START = "2019-01-01"

ACCEPTANCE = {
    "min_profit_factor": 1.20,
    "min_positive_fold_pct": 60.0,
    "max_drawdown_limit_pct": -25.0,
    "max_fold_dominance_pct": 60.0,
    "min_trades": 25,
    "min_stress_positive_fold_pct": 50.0,
}


def _score(metrics: dict) -> float:
    """Training-fold objective. Never sees test data."""
    if metrics["trade_count"] < 5:
        return float("-inf")
    return float(metrics["sharpe"]) + 0.25 * min(float(metrics["calmar"]), 3.0)


def _stitch(curves: list[list[dict]]) -> list[dict]:
    """Chain fold curves into one continuous out-of-sample equity path."""
    stitched: list[dict] = []
    level = 1.0
    for curve in curves:
        if not curve:
            continue
        base = float(curve[0]["equity"]) or 1.0
        points = curve if not stitched else curve[1:]
        for point in points:
            stitched.append({
                "timestamp": point["timestamp"],
                "equity": level * float(point["equity"]) / base,
            })
        if stitched:
            level = float(stitched[-1]["equity"])
    return stitched


def _panel_for(
    raw: dict[str, pd.DataFrame],
    cfg: BacktestConfig,
    cache: dict[tuple, data.Panel],
) -> data.Panel:
    key = (cfg.trend_ema_period, tuple(cfg.momentum_lookbacks))
    if key not in cache:
        frames = data.apply_indicators(raw, **cfg.indicator_params())
        cache[key] = data.align_panel(frames)
    return cache[key]


def _candidates(base: BacktestConfig) -> list[BacktestConfig]:
    return [
        replace(
            base,
            momentum_lookbacks=momentum,
            trend_ema_period=trend,
            rank_buffer=rank_buffer,
            min_hold_days=min_hold,
            min_history_bars=max(base.min_history_bars, trend + 10),
        )
        for momentum, trend, rank_buffer, min_hold in product(
            MOMENTUM_GRID, TREND_GRID, RANK_BUFFER_GRID, MIN_HOLD_GRID
        )
    ]


def run_walk_forward(
    raw_frames: dict[str, pd.DataFrame],
    base_config: BacktestConfig,
    *,
    on_progress=None,
) -> dict:
    panel_cache: dict[tuple, data.Panel] = {}
    candidates = _candidates(base_config)
    reference = _panel_for(raw_frames, base_config, panel_cache)

    first = max(
        reference.dates[0],
        pd.Timestamp(VALIDATION_START, tz="UTC"),
    )
    last = reference.dates[-1]

    folds: list[dict] = []
    test_curves: list[list[dict]] = []
    benchmark_curves: list[list[dict]] = []
    train_start = first

    while train_start + pd.DateOffset(months=TRAIN_MONTHS + TEST_MONTHS) <= last:
        train_end = train_start + pd.DateOffset(months=TRAIN_MONTHS)
        test_end = min(train_end + pd.DateOffset(months=TEST_MONTHS), last)

        best_score = float("-inf")
        best_cfg: BacktestConfig | None = None
        best_train: dict | None = None
        for candidate in candidates:
            panel = _panel_for(raw_frames, candidate, panel_cache)
            try:
                train_window = panel.slice_dates(train_start, train_end)
            except ValueError:
                continue
            if len(train_window) < MIN_TRAIN_BARS:
                continue
            train_result = run_backtest(train_window, candidate)
            train_metrics = calculate_metrics(train_result, train_window, candidate)
            score = _score(train_metrics)
            if score > best_score:
                best_score, best_cfg, best_train = score, candidate, train_metrics

        if best_cfg is None:
            train_start += pd.DateOffset(months=STEP_MONTHS)
            continue

        panel = _panel_for(raw_frames, best_cfg, panel_cache)
        test_window = panel.slice_dates(train_end, test_end)
        test_result = run_backtest(test_window, best_cfg)
        test_metrics = calculate_metrics(test_result, test_window, best_cfg)

        stress_cfg = best_cfg.with_costs(0.002, 10.0)
        stress_result = run_backtest(test_window, stress_cfg)
        stress_metrics = calculate_metrics(stress_result, test_window, stress_cfg)

        benchmark = buy_and_hold(
            test_window,
            best_cfg.regime_symbol,
            best_cfg.initial_capital,
            best_cfg.fee_rate,
        )
        test_curves.append(test_result.equity_curve)
        benchmark_curves.append(benchmark["curve"])

        folds.append({
            "train_from": str(train_start.date()),
            "train_to": str(train_end.date()),
            "test_from": str(train_end.date()),
            "test_to": str(test_end.date()),
            "selected": {
                "momentum_lookbacks": list(best_cfg.momentum_lookbacks),
                "trend_ema_period": best_cfg.trend_ema_period,
                "rank_buffer": best_cfg.rank_buffer,
                "min_hold_days": best_cfg.min_hold_days,
            },
            "train": best_train,
            "test": test_metrics,
            "stress": stress_metrics,
            "benchmark": {
                "total_return_pct": benchmark["total_return_pct"],
                "max_drawdown_pct": benchmark["max_drawdown_pct"],
                "sharpe": benchmark["sharpe"],
            },
        })
        if on_progress:
            on_progress(folds[-1])
        train_start += pd.DateOffset(months=STEP_MONTHS)

    if not folds:
        raise ValueError(
            f"Not enough history for a single fold "
            f"({TRAIN_MONTHS}m train + {TEST_MONTHS}m test required)."
        )

    stitched = _stitch(test_curves)
    stitched_benchmark = _stitch(benchmark_curves)
    oos = equity_stats(stitched)
    oos.pop("years", None)
    benchmark_oos = equity_stats(stitched_benchmark)
    benchmark_oos.pop("years", None)

    returns = [fold["test"]["total_return_pct"] / 100 for fold in folds]
    gross_profit = sum(fold["test"]["gross_profit_usdt"] for fold in folds)
    gross_loss = sum(fold["test"]["gross_loss_usdt"] for fold in folds)
    trades = sum(fold["test"]["trade_count"] for fold in folds)
    expectancy = (
        sum(
            fold["test"]["expectancy_usdt"] * fold["test"]["trade_count"]
            for fold in folds
        )
        / trades
        if trades
        else 0.0
    )
    positive = [value for value in returns if value > 0]
    total_positive = sum(positive)
    dominance = (max(positive) / total_positive * 100) if total_positive else 100.0

    aggregate = {
        "return_pct": oos["total_return_pct"],
        "cagr_pct": oos["cagr_pct"],
        "sharpe": oos["sharpe"],
        "sortino": oos["sortino"],
        "max_drawdown_pct": oos["max_drawdown_pct"],
        "calmar": oos["calmar"],
        "profit_factor": gross_profit / gross_loss if gross_loss else 0.0,
        "expectancy_usdt": expectancy,
        "positive_fold_pct": len(positive) / len(returns) * 100,
        "trade_count": trades,
        "fold_count": len(folds),
        "largest_fold_profit_share_pct": dominance,
        "stress_positive_fold_pct": (
            sum(fold["stress"]["total_return_pct"] > 0 for fold in folds)
            / len(folds)
            * 100
        ),
        "benchmark_return_pct": benchmark_oos["total_return_pct"],
        "benchmark_sharpe": benchmark_oos["sharpe"],
        "benchmark_max_drawdown_pct": benchmark_oos["max_drawdown_pct"],
        "benchmark_symbol": base_config.regime_symbol,
    }

    gates = {
        "profit_factor": aggregate["profit_factor"] > ACCEPTANCE["min_profit_factor"],
        "positive_expectancy": aggregate["expectancy_usdt"] > 0,
        "fold_consistency": (
            aggregate["positive_fold_pct"] >= ACCEPTANCE["min_positive_fold_pct"]
        ),
        "max_drawdown_absolute": (
            aggregate["max_drawdown_pct"] >= ACCEPTANCE["max_drawdown_limit_pct"]
        ),
        "max_drawdown_beats_benchmark": (
            aggregate["max_drawdown_pct"] > aggregate["benchmark_max_drawdown_pct"]
        ),
        "sharpe_beats_benchmark": (
            aggregate["sharpe"] > aggregate["benchmark_sharpe"]
        ),
        "not_fold_dominated": (
            aggregate["largest_fold_profit_share_pct"]
            <= ACCEPTANCE["max_fold_dominance_pct"]
        ),
        "minimum_trades": aggregate["trade_count"] >= ACCEPTANCE["min_trades"],
        "survives_stress_costs": (
            aggregate["stress_positive_fold_pct"]
            >= ACCEPTANCE["min_stress_positive_fold_pct"]
        ),
    }

    return {
        "config": asdict(base_config),
        "acceptance": ACCEPTANCE,
        "folds": folds,
        "aggregate": aggregate,
        "gates": gates,
        "accepted": all(gates.values()),
        "oos_curve": stitched,
        "benchmark_curve": stitched_benchmark,
    }
