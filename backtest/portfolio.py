"""Equal-weight 3-bot portfolio correlation and equity-curve smoothness check.

Combines Orbit (1D crypto), Gold (1H), and MNQ (15m) out-of-sample equity
curves on a shared daily grid. Pairwise return correlations measure
diversification; the equal-weight portfolio of available daily returns is
scored for Sharpe, profit factor, and drawdown smoothness.

Orbit strategy rules are never modified here — only equity curves are read.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .metrics import equity_stats

BOT_KEYS = ("orbit", "gold", "mnq")

ACCEPTANCE = {
    "min_sharpe": 0.50,
    "min_profit_factor": 1.20,
    "max_pairwise_corr": 0.50,
    "min_overlap_days_pair": 10,
}


def curve_to_daily(curve: Sequence[Mapping[str, Any]]) -> pd.Series:
    """Resample an equity curve to last observation per UTC day."""
    frame = pd.DataFrame(list(curve))
    if frame.empty:
        return pd.Series(dtype=float)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    equity = (
        frame.set_index("timestamp")["equity"]
        .astype(float)
        .sort_index()
        .resample("1D")
        .last()
        .dropna()
    )
    return equity


def daily_returns(equity: pd.Series) -> pd.Series:
    if equity.empty:
        return pd.Series(dtype=float)
    return equity.pct_change()


def pairwise_correlations(
    returns: Mapping[str, pd.Series],
    *,
    min_overlap: int = 10,
) -> dict[str, dict[str, float | int | None]]:
    """Pearson correlation of daily returns for every bot pair."""
    keys = [k for k in BOT_KEYS if k in returns]
    out: dict[str, dict[str, float | int | None]] = {}
    for i, left in enumerate(keys):
        for right in keys[i + 1 :]:
            joined = pd.concat(
                [returns[left].rename(left), returns[right].rename(right)],
                axis=1,
                join="inner",
            ).dropna()
            label = f"{left}_{right}"
            if len(joined) < min_overlap:
                out[label] = {
                    "correlation": None,
                    "overlap_days": int(len(joined)),
                    "usable": False,
                }
                continue
            std_l = float(joined[left].std(ddof=0))
            std_r = float(joined[right].std(ddof=0))
            if std_l == 0.0 or std_r == 0.0:
                out[label] = {
                    "correlation": None,
                    "overlap_days": int(len(joined)),
                    "usable": False,
                }
                continue
            corr = float(joined[left].corr(joined[right]))
            out[label] = {
                "correlation": corr,
                "overlap_days": int(len(joined)),
                "usable": True,
            }
    return out


def equal_weight_portfolio_returns(
    returns: Mapping[str, pd.Series],
) -> pd.Series:
    """Mean of available bot daily returns on each calendar day."""
    frame = pd.concat(
        {name: series for name, series in returns.items() if not series.empty},
        axis=1,
        join="outer",
    ).sort_index()
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.mean(axis=1, skipna=True).dropna()


def equity_from_returns(returns: pd.Series, initial: float = 1.0) -> list[dict]:
    if returns.empty:
        return []
    level = initial * (1.0 + returns).cumprod()
    return [
        {"timestamp": str(ts), "equity": float(val)}
        for ts, val in level.items()
    ]


def multi_bot_smoothness(
    returns: Mapping[str, pd.Series],
) -> dict[str, float | bool | int]:
    """Portfolio vol vs average bot vol on days with at least two live bots."""
    frame = pd.concat(
        {name: series for name, series in returns.items() if not series.empty},
        axis=1,
        join="outer",
    ).sort_index()
    if frame.empty:
        return {
            "multi_bot_days": 0,
            "portfolio_vol": 0.0,
            "avg_bot_vol": 0.0,
            "smoother": False,
        }
    mask = frame.notna().sum(axis=1) >= 2
    sub = frame.loc[mask]
    if sub.empty or len(sub) < 5:
        return {
            "multi_bot_days": int(len(sub)),
            "portfolio_vol": 0.0,
            "avg_bot_vol": 0.0,
            "smoother": False,
        }
    port = sub.mean(axis=1)
    port_vol = float(port.std(ddof=0))
    avg_vol = float(sub.std(ddof=0).mean())
    return {
        "multi_bot_days": int(len(sub)),
        "portfolio_vol": port_vol,
        "avg_bot_vol": avg_vol,
        "smoother": bool(port_vol < avg_vol),
    }


def combined_profit_factor(bot_payloads: Mapping[str, Mapping[str, Any]]) -> float:
    """Sum fold-level gross profit / loss across bots when available."""
    gross_p = 0.0
    gross_l = 0.0
    for payload in bot_payloads.values():
        folds = payload.get("folds") or []
        if folds:
            for fold in folds:
                test = fold.get("test") or {}
                gross_p += float(test.get("gross_profit_usdt") or 0.0)
                gross_l += float(test.get("gross_loss_usdt") or 0.0)
            continue
        agg = payload.get("aggregate") or {}
        pf = float(agg.get("profit_factor") or 0.0)
        trades = int(agg.get("trade_count") or 0)
        # Recover approximate grosses when only PF is stored.
        if pf > 0 and trades > 0:
            # Unit gross loss; scale cancels in the ratio.
            gross_p += pf
            gross_l += 1.0
    if gross_l <= 0:
        return math.inf if gross_p > 0 else 0.0
    return gross_p / gross_l


def load_walk_forward_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_portfolio_check(
    bot_curves: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    bot_payloads: Mapping[str, Mapping[str, Any]] | None = None,
    acceptance: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Score the 3-bot desk for diversification and a smooth combined curve."""
    gates_cfg = dict(ACCEPTANCE)
    if acceptance:
        gates_cfg.update(acceptance)

    daily: dict[str, pd.Series] = {}
    returns: dict[str, pd.Series] = {}
    individual: dict[str, dict[str, float]] = {}
    for name in BOT_KEYS:
        curve = bot_curves.get(name) or []
        eq = curve_to_daily(curve)
        daily[name] = eq
        returns[name] = daily_returns(eq)
        if len(eq) >= 2:
            stats = equity_stats(
                [{"timestamp": str(ts), "equity": float(v)} for ts, v in eq.items()]
            )
            individual[name] = {
                "days": float(len(eq)),
                "sharpe": float(stats["sharpe"]),
                "max_drawdown_pct": float(stats["max_drawdown_pct"]),
                "total_return_pct": float(stats["total_return_pct"]),
            }
        else:
            individual[name] = {
                "days": float(len(eq)),
                "sharpe": 0.0,
                "max_drawdown_pct": 0.0,
                "total_return_pct": 0.0,
            }

    corr = pairwise_correlations(
        returns, min_overlap=int(gates_cfg["min_overlap_days_pair"])
    )
    usable_corrs = [
        float(row["correlation"])
        for row in corr.values()
        if row.get("usable") and row.get("correlation") is not None
    ]
    max_corr = max(usable_corrs) if usable_corrs else 0.0
    mean_corr = float(np.mean(usable_corrs)) if usable_corrs else 0.0

    port_rets = equal_weight_portfolio_returns(returns)
    port_curve = equity_from_returns(port_rets)
    if len(port_curve) >= 2:
        port_stats = equity_stats(port_curve)
    else:
        port_stats = {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "annual_volatility_pct": 0.0,
            "years": 0.0,
        }

    smooth = multi_bot_smoothness(returns)
    payloads = bot_payloads or {}
    profit_factor = combined_profit_factor(payloads) if payloads else 0.0

    worst_dd = min(
        (float(row["max_drawdown_pct"]) for row in individual.values()),
        default=0.0,
    )
    dd_improved = float(port_stats["max_drawdown_pct"]) > worst_dd

    aggregate = {
        "return_pct": float(port_stats["total_return_pct"]),
        "cagr_pct": float(port_stats["cagr_pct"]),
        "sharpe": float(port_stats["sharpe"]),
        "sortino": float(port_stats["sortino"]),
        "max_drawdown_pct": float(port_stats["max_drawdown_pct"]),
        "profit_factor": float(profit_factor),
        "max_pairwise_corr": float(max_corr),
        "mean_pairwise_corr": float(mean_corr),
        "portfolio_days": int(len(port_curve)),
        "worst_bot_drawdown_pct": float(worst_dd),
        "drawdown_beats_worst_bot": bool(dd_improved),
        **{f"smooth_{k}": v for k, v in smooth.items()},
    }

    gates = {
        "min_sharpe": aggregate["sharpe"] > gates_cfg["min_sharpe"],
        "min_profit_factor": aggregate["profit_factor"] > gates_cfg["min_profit_factor"],
        "max_pairwise_corr": aggregate["max_pairwise_corr"]
        < gates_cfg["max_pairwise_corr"],
        "smooth_multi_bot_vol": bool(smooth["smoother"]),
        "drawdown_beats_worst_bot": dd_improved,
        "has_pairwise_signal": len(usable_corrs) >= 1,
    }

    return {
        "acceptance": gates_cfg,
        "bots": individual,
        "correlations": corr,
        "aggregate": aggregate,
        "gates": gates,
        "accepted": all(gates.values()),
        "equity_curve": port_curve,
    }


def run_from_walk_forward_dir(output_dir: Path) -> dict[str, Any]:
    """Load the three local walk-forward JSON files and score the desk."""
    paths = {
        "orbit": output_dir / "walk_forward.json",
        "gold": output_dir / "walk_forward_gold.json",
        "mnq": output_dir / "walk_forward_mnq.json",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing walk-forward outputs (run the local WF runners first): "
            + ", ".join(missing)
        )
    payloads = {name: load_walk_forward_payload(path) for name, path in paths.items()}
    curves = {name: payload.get("oos_curve") or [] for name, payload in payloads.items()}
    result = run_portfolio_check(curves, bot_payloads=payloads)
    result["sources"] = {name: str(path) for name, path in paths.items()}
    return result
