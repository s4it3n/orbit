"""Unit tests for the 3-bot portfolio correlation helper."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.portfolio import (
    combined_profit_factor,
    curve_to_daily,
    equal_weight_portfolio_returns,
    multi_bot_smoothness,
    pairwise_correlations,
    run_portfolio_check,
)


def _curve(start: str, values: list[float], freq: str = "1D") -> list[dict]:
    stamps = pd.date_range(start, periods=len(values), freq=freq, tz="UTC")
    return [{"timestamp": str(ts), "equity": float(v)} for ts, v in zip(stamps, values)]


def test_curve_to_daily_resamples_intraday():
    # Three bars on day 1, three on day 2 (12h spacing crosses midnight).
    stamps = pd.date_range("2024-01-01 00:00", periods=6, freq="12h", tz="UTC")
    curve = [
        {"timestamp": str(stamps[0]), "equity": 100.0},
        {"timestamp": str(stamps[1]), "equity": 101.0},
        {"timestamp": str(stamps[2]), "equity": 102.0},  # 2024-01-02 00:00
        {"timestamp": str(stamps[3]), "equity": 103.0},
        {"timestamp": str(stamps[4]), "equity": 104.0},  # 2024-01-03 00:00
        {"timestamp": str(stamps[5]), "equity": 105.0},
    ]
    daily = curve_to_daily(curve)
    assert len(daily) == 3
    assert float(daily.iloc[0]) == 101.0
    assert float(daily.iloc[1]) == 103.0
    assert float(daily.iloc[2]) == 105.0


def test_pairwise_low_correlation_and_smooth_portfolio():
    rng = np.random.default_rng(7)
    n = 120
    common = rng.normal(0.0005, 0.002, n)
    # Nearly independent residual shocks → low pairwise corr, portfolio smoother.
    orbit = 100 * np.cumprod(1 + common * 0.1 + rng.normal(0, 0.01, n))
    gold = 100 * np.cumprod(1 + common * 0.1 + rng.normal(0, 0.008, n))
    mnq = 100 * np.cumprod(1 + common * 0.1 + rng.normal(0, 0.012, n))

    curves = {
        "orbit": _curve("2024-01-01", orbit.tolist()),
        "gold": _curve("2024-01-01", gold.tolist()),
        "mnq": _curve("2024-01-01", mnq.tolist()),
    }
    payloads = {
        "orbit": {
            "folds": [{"test": {"gross_profit_usdt": 130.0, "gross_loss_usdt": 100.0}}],
            "aggregate": {"profit_factor": 1.3, "trade_count": 10},
        },
        "gold": {
            "folds": [{"test": {"gross_profit_usdt": 140.0, "gross_loss_usdt": 100.0}}],
            "aggregate": {"profit_factor": 1.4, "trade_count": 10},
        },
        "mnq": {
            "folds": [{"test": {"gross_profit_usdt": 125.0, "gross_loss_usdt": 100.0}}],
            "aggregate": {"profit_factor": 1.25, "trade_count": 10},
        },
    }
    result = run_portfolio_check(curves, bot_payloads=payloads)
    assert result["aggregate"]["max_pairwise_corr"] < 0.50
    assert result["aggregate"]["smooth_smoother"] is True
    assert result["aggregate"]["profit_factor"] > 1.20
    assert result["gates"]["has_pairwise_signal"] is True
    assert result["gates"]["max_pairwise_corr"] is True
    assert result["gates"]["smooth_multi_bot_vol"] is True
    assert result["gates"]["min_profit_factor"] is True


def test_combined_profit_factor_sums_fold_gross():
    payloads = {
        "a": {"folds": [{"test": {"gross_profit_usdt": 200.0, "gross_loss_usdt": 100.0}}]},
        "b": {"folds": [{"test": {"gross_profit_usdt": 100.0, "gross_loss_usdt": 100.0}}]},
    }
    assert abs(combined_profit_factor(payloads) - 1.5) < 1e-9


def test_equal_weight_skips_missing_bots():
    orbit = pd.Series(
        [0.01, 0.02, -0.01],
        index=pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC"),
    )
    gold = pd.Series(
        [0.00, np.nan, 0.03],
        index=pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC"),
    )
    port = equal_weight_portfolio_returns({"orbit": orbit, "gold": gold})
    assert abs(float(port.iloc[0]) - 0.005) < 1e-12  # (0.01+0)/2
    assert abs(float(port.iloc[1]) - 0.02) < 1e-12  # only orbit
    assert abs(float(port.iloc[2]) - 0.01) < 1e-12  # (-0.01+0.03)/2


def test_smoothness_requires_multi_bot_days():
    idx = pd.date_range("2024-01-01", periods=30, freq="1D", tz="UTC")
    rng = np.random.default_rng(0)
    noisy = pd.Series(rng.normal(0, 0.02, 30), index=idx)
    alone = multi_bot_smoothness({"orbit": noisy})
    assert alone["smoother"] is False
    # Independent second stream → equal-weight vol drops below average bot vol.
    other = pd.Series(rng.normal(0, 0.02, 30), index=idx)
    both = multi_bot_smoothness({"orbit": noisy, "gold": other})
    assert both["multi_bot_days"] == 30
    assert both["smoother"] is True
