"""Walk-forward validation for the Gold 1H Donchian squeeze breakout."""

from __future__ import annotations

from dataclasses import asdict, replace
from itertools import product

import pandas as pd

from gold_bot import strategy as gold_strategy
from gold_bot.engine import metrics_from_result, run_backtest

TRAIN_MONTHS = 6
TEST_MONTHS = 2
STEP_MONTHS = 2
MIN_TRAIN_BARS = 800
MIN_TEST_BARS = 200

ACCEPTANCE = {
    "min_return_pct": 0.0,
    "min_sharpe": 0.50,
    "min_trades": 15,
}


def _candidates(base: gold_strategy.GoldRules) -> list[gold_strategy.GoldRules]:
    return [
        replace(
            base,
            donchian_period=donchian,
            breakout_atr_mult=brk,
            initial_stop_atr=stop,
            trail_atr=trail,
            squeeze_min_bars=squeeze_bars,
            trend_sma_period=trend,
            long_only=long_only,
            session_start_hour=session[0],
            session_end_hour=session[1],
            require_inside_prev=inside,
            time_stop_hours=time_stop,
        )
        for donchian, brk, stop, trail, squeeze_bars, trend, long_only, session, inside, time_stop in product(
            (24,),
            (0.2,),
            (2.0, 2.5),
            (3.0,),
            (1, 4),
            (0, 200),
            (True, False),
            ((None, None),),
            (True,),
            (48,),
        )
    ]


def _score(metrics: dict) -> float:
    if metrics["trade_count"] < 8:
        return float("-inf")
    if metrics["total_return_pct"] <= -5:
        return float("-inf")
    return float(metrics["sharpe_ratio"]) + 0.02 * float(metrics["total_return_pct"])


def _slice(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    out = frame.loc[(ts >= start) & (ts < end)].copy()
    return out.reset_index(drop=True)


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


def _curve_stats(curve: list[dict], initial_capital: float = 1.0) -> dict[str, float]:
    if not curve:
        return {"return_pct": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0, "win_rate_pct": 0.0}
    fake = type("R", (), {
        "equity_curve": curve,
        "initial_capital": float(curve[0]["equity"]) or initial_capital,
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
    base: gold_strategy.GoldRules | None = None,
    *,
    initial_capital: float = 100_000.0,
    on_progress=None,
) -> dict:
    rules0 = base or gold_strategy.GoldRules()
    candidates = _candidates(rules0)
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    first = ts.iloc[0]
    last = ts.iloc[-1]

    folds: list[dict] = []
    test_curves: list[list[dict]] = []
    train_start = first

    while train_start + pd.DateOffset(months=TRAIN_MONTHS + TEST_MONTHS) <= last:
        train_end = train_start + pd.DateOffset(months=TRAIN_MONTHS)
        test_end = min(train_end + pd.DateOffset(months=TEST_MONTHS), last)
        train = _slice(frame, train_start, train_end)
        test = _slice(frame, train_end, test_end)
        if len(train) < MIN_TRAIN_BARS or len(test) < MIN_TEST_BARS:
            train_start += pd.DateOffset(months=STEP_MONTHS)
            continue

        best_score = float("-inf")
        best_rules: gold_strategy.GoldRules | None = None
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
            train_start += pd.DateOffset(months=STEP_MONTHS)
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
        train_start += pd.DateOffset(months=STEP_MONTHS)

    if not folds:
        raise ValueError("Not enough gold history for a walk-forward fold.")

    stitched = stitch_curves(test_curves)
    oos = _curve_stats(stitched)
    trades = sum(int(f["test"]["trade_count"]) for f in folds)
    wins = 0
    pnls = 0.0
    gross_p = 0.0
    gross_l = 0.0
    win_rates = []
    for fold in folds:
        t = fold["test"]
        win_rates.append(float(t["win_rate_pct"]))
        n = int(t["trade_count"])
        pf = float(t["profit_factor"])
        # Reconstruct approximate gross from PF is unstable; use fold expectancy.
        pnls += float(t["expectancy_usdt"]) * n
        gross_p += float(t["gross_profit_usdt"])
        gross_l += float(t["gross_loss_usdt"])
        wins += 1 if t["total_return_pct"] > 0 else 0

    aggregate = {
        "return_pct": oos["return_pct"],
        "sharpe": oos["sharpe"],
        "max_drawdown_pct": oos["max_drawdown_pct"],
        "win_rate_pct": sum(win_rates) / len(win_rates) if win_rates else 0.0,
        "profit_factor": (gross_p / gross_l) if gross_l else 0.0,
        "trade_count": trades,
        "fold_count": len(folds),
        "positive_fold_pct": wins / len(folds) * 100,
        "expectancy_usdt": pnls / trades if trades else 0.0,
    }
    gates = {
        "positive_return": aggregate["return_pct"] > ACCEPTANCE["min_return_pct"],
        "min_sharpe": aggregate["sharpe"] > ACCEPTANCE["min_sharpe"],
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
