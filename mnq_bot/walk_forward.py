"""Walk-forward validation for the MNQ 15m opening-range breakout."""

from __future__ import annotations

from dataclasses import asdict, replace

import pandas as pd

from mnq_bot import strategy as mnq_strategy
from mnq_bot.engine import metrics_from_result, run_backtest

TRAIN_DAYS = 28
TEST_DAYS = 7
STEP_DAYS = 7
MIN_TRAIN_BARS = 500
MIN_TEST_BARS = 80

ACCEPTANCE = {
    "min_return_pct": 0.0,
    "min_sharpe": 0.50,
    "min_profit_factor": 1.20,
    "min_trades": 6,
}


# CET opening-range windows under comparison:
#   15:30-15:45  -> duration 15, entries from 15:45
#   15:30-16:00  -> duration 30, entries from 16:00
OR_WINDOWS = (
    {"or_duration_minutes": 15, "entry_start_hour_cet": 15, "entry_start_minute_cet": 45},
    {"or_duration_minutes": 30, "entry_start_hour_cet": 16, "entry_start_minute_cet": 0},
)


def _candidates(base: mnq_strategy.MnqRules) -> list[mnq_strategy.MnqRules]:
    """ORB family × CET OR windows (15 vs 30 min). Keep grid small for short trains."""
    specs = [
        {"use_vwap": True, "session_bias": False, "max_or_points": 250.0, "volume_mult": 1.25, "long_only": False, "reward_risk": 2.0},
        {"use_vwap": True, "session_bias": False, "max_or_points": 160.0, "volume_mult": 1.25, "long_only": False, "reward_risk": 2.0},
        {"use_vwap": False, "session_bias": False, "max_or_points": 250.0, "volume_mult": 1.0, "long_only": False, "reward_risk": 2.0},
        {"use_vwap": True, "session_bias": True, "max_or_points": 250.0, "volume_mult": 1.25, "long_only": False, "reward_risk": 2.0},
    ]
    out: list[mnq_strategy.MnqRules] = []
    for window in OR_WINDOWS:
        for spec in specs:
            out.append(
                replace(
                    base,
                    or_hour_cet=15,
                    or_minute_cet=30,
                    breakout_points=2.0,
                    or_min_atr_mult=0.15,
                    or_max_atr_mult=5.0,
                    min_or_points=12.0,
                    trend_sma_period=0,
                    entry_end_hour_cet=18,
                    entry_end_minute_cet=0,
                    **window,
                    **spec,
                )
            )
    return out


def _score(metrics: dict) -> float:
    if metrics["trade_count"] < 4:
        return float("-inf")
    return float(metrics["profit_factor"]) + 0.05 * float(metrics["total_return_pct"])


def _slice(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.loc[(ts >= start) & (ts < end)].copy().reset_index(drop=True)


def stitch_curves(curves: list[list[dict]]) -> list[dict]:
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


def _curve_stats(curve: list[dict]) -> dict[str, float]:
    if not curve:
        return {"return_pct": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0, "win_rate_pct": 0.0}
    fake = type("R", (), {
        "equity_curve": curve,
        "initial_capital": float(curve[0]["equity"]) or 1.0,
        "trades": [],
    })()
    metrics = metrics_from_result(fake)  # type: ignore[arg-type]
    return {
        "return_pct": metrics["total_return_pct"],
        "sharpe": metrics["sharpe_ratio"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "win_rate_pct": metrics["win_rate_pct"],
    }


def run_walk_forward(
    frame: pd.DataFrame,
    base: mnq_strategy.MnqRules | None = None,
    *,
    initial_capital: float = 50_000.0,
    on_progress=None,
) -> dict:
    rules0 = base or mnq_strategy.MnqRules()
    candidates = _candidates(rules0)
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    first = ts.iloc[0]
    last = ts.iloc[-1]

    folds: list[dict] = []
    test_curves: list[list[dict]] = []
    train_start = first

    while train_start + pd.Timedelta(days=TRAIN_DAYS + TEST_DAYS) <= last:
        train_end = train_start + pd.Timedelta(days=TRAIN_DAYS)
        test_end = min(train_end + pd.Timedelta(days=TEST_DAYS), last)
        train = _slice(frame, train_start, train_end)
        test = _slice(frame, train_end, test_end)
        if len(train) < MIN_TRAIN_BARS or len(test) < MIN_TEST_BARS:
            train_start += pd.Timedelta(days=STEP_DAYS)
            continue

        best_score = float("-inf")
        best_rules: mnq_strategy.MnqRules | None = None
        best_train: dict | None = None
        for candidate in candidates:
            train_result = run_backtest(train, initial_capital=initial_capital, rules=candidate)
            train_metrics = metrics_from_result(train_result)
            score = _score(train_metrics)
            if score > best_score:
                best_score = score
                best_rules = candidate
                best_train = train_metrics

        if best_rules is None:
            train_start += pd.Timedelta(days=STEP_DAYS)
            continue

        test_result = run_backtest(test, initial_capital=initial_capital, rules=best_rules)
        test_metrics = metrics_from_result(test_result)
        test_curves.append(test_result.equity_curve)
        fold = {
            "train_from": str(train_start.date()),
            "train_to": str(train_end.date()),
            "test_from": str(train_end.date()),
            "test_to": str(pd.Timestamp(test_end).date()),
            "selected": asdict(best_rules),
            "train": best_train,
            "test": test_metrics,
        }
        folds.append(fold)
        if on_progress:
            on_progress(fold)
        train_start += pd.Timedelta(days=STEP_DAYS)

    if not folds:
        raise ValueError("Not enough MNQ history for a walk-forward fold.")

    stitched = stitch_curves(test_curves)
    oos = _curve_stats(stitched)
    trades = sum(int(f["test"]["trade_count"]) for f in folds)
    wins = sum(1 for f in folds if f["test"]["total_return_pct"] > 0)
    gross_p = sum(float(f["test"]["gross_profit_usdt"]) for f in folds)
    gross_l = sum(float(f["test"]["gross_loss_usdt"]) for f in folds)
    win_rates = [float(f["test"]["win_rate_pct"]) for f in folds]
    or_counts: dict[int, int] = {}
    for fold in folds:
        dur = int(fold["selected"].get("or_duration_minutes", 15))
        or_counts[dur] = or_counts.get(dur, 0) + 1
    preferred_or = max(or_counts, key=or_counts.get) if or_counts else 15

    aggregate = {
        "return_pct": oos["return_pct"],
        "sharpe": oos["sharpe"],
        "max_drawdown_pct": oos["max_drawdown_pct"],
        "win_rate_pct": sum(win_rates) / len(win_rates) if win_rates else 0.0,
        "profit_factor": (gross_p / gross_l) if gross_l else 0.0,
        "trade_count": trades,
        "fold_count": len(folds),
        "positive_fold_pct": wins / len(folds) * 100,
        "or_window_fold_counts": {str(k): v for k, v in sorted(or_counts.items())},
        "preferred_or_duration_minutes": preferred_or,
    }
    gates = {
        "positive_return": aggregate["return_pct"] > ACCEPTANCE["min_return_pct"],
        "min_sharpe": aggregate["sharpe"] > ACCEPTANCE["min_sharpe"],
        "min_profit_factor": aggregate["profit_factor"] > ACCEPTANCE["min_profit_factor"],
        "minimum_trades": aggregate["trade_count"] >= ACCEPTANCE["min_trades"],
    }
    return {
        "config": asdict(rules0),
        "acceptance": ACCEPTANCE,
        "folds": folds,
        "aggregate": aggregate,
        "gates": gates,
        "accepted": all(gates.values()),
        "oos_curve": stitched,
    }
