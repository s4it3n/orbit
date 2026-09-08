"""Shared paper-trading cost model (fees + adverse slippage).

Goal: live paper P&L should feel like a real small retail desk, not a
frictionless backtest. Numbers are env-overridable and intentionally a bit
conservative vs the absolute cheapest venues.
"""

from __future__ import annotations

import os
from typing import Literal


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    return float(raw)


# Crypto spot (Binance-class retail taker + a little adverse slip).
ORBIT_FEE_RATE = _env_float("ORBIT_FEE_RATE", 0.001)  # 10 bps
ORBIT_SLIPPAGE_BPS = _env_float("ORBIT_SLIPPAGE_BPS", 5.0)

# Gold CFD / micro futures proxy — spread+comm all-in per side.
GOLD_COST_BPS = _env_float("GOLD_COST_BPS", 2.0)  # 2 bps/side
GOLD_SLIPPAGE_BPS = _env_float("GOLD_SLIPPAGE_BPS", 1.0)

# QQQ ETF / Nasdaq-100 day desk — commission-free retail + small adverse slip.
# (Legacy MNQ_* env names still accepted as aliases.)
QQQ_COST_BPS = _env_float(
    "QQQ_COST_BPS",
    _env_float("MNQ_COST_BPS", 1.0),  # 1 bps/side ≈ cheap retail ETF
)
QQQ_SLIPPAGE_BPS = _env_float(
    "QQQ_SLIPPAGE_BPS",
    _env_float("MNQ_SLIPPAGE_BPS", 2.0),
)
# Kept for older scripts; unused by QQQ share sizing.
MNQ_MIN_MARGIN = _env_float("MNQ_MIN_MARGIN", 0.0)
MNQ_COMMISSION = _env_float("MNQ_COMMISSION", 0.0)
MNQ_SLIPPAGE_PTS = _env_float("MNQ_SLIPPAGE_PTS", 0.0)
MNQ_POINT_VALUE = 1.0  # share PnL is 1:1 with price dollars


Side = Literal["buy", "sell"]


def notional_fee(notional: float, *, fee_rate: float | None = None) -> float:
    rate = ORBIT_FEE_RATE if fee_rate is None else fee_rate
    return max(0.0, abs(float(notional)) * float(rate))


def notional_slip(notional: float, *, slip_bps: float | None = None) -> float:
    bps = ORBIT_SLIPPAGE_BPS if slip_bps is None else slip_bps
    return max(0.0, abs(float(notional)) * float(bps) / 10_000.0)


def crypto_round_trip_drag(notional: float) -> float:
    """Fee + slip cost for one market fill (one side)."""
    return notional_fee(notional) + notional_slip(notional)


def effective_crypto_fee(reported_fee: float, notional: float) -> float:
    """Prefer exchange-reported fee; floor at modeled retail taker if testnet undercharges."""
    return max(float(reported_fee or 0.0), notional_fee(notional))


def gold_side_cost(qty: float, price: float, *, cost_bps: float | None = None) -> float:
    bps = GOLD_COST_BPS if cost_bps is None else cost_bps
    return abs(float(qty)) * float(price) * float(bps) / 10_000.0


def gold_fill_price(price: float, side: str, *, slip_bps: float | None = None) -> float:
    """Adverse mid→fill: longs pay up, shorts sell down (and the reverse on exit)."""
    bps = GOLD_SLIPPAGE_BPS if slip_bps is None else slip_bps
    px = float(price)
    slip = px * float(bps) / 10_000.0
    if side in {"buy", "long", "cover"}:
        return px + slip
    return px - slip


def qqq_side_cost(qty: float, price: float, *, cost_bps: float | None = None) -> float:
    bps = QQQ_COST_BPS if cost_bps is None else cost_bps
    return abs(float(qty)) * float(price) * float(bps) / 10_000.0


def qqq_fill_price(price: float, side: str, *, slip_bps: float | None = None) -> float:
    bps = QQQ_SLIPPAGE_BPS if slip_bps is None else slip_bps
    px = float(price)
    slip = px * float(bps) / 10_000.0
    if side in {"buy", "long", "cover"}:
        return px + slip
    return px - slip


# Back-compat aliases used by older tests / imports.
def mnq_commission(qty: float, *, per_side: float | None = None) -> float:
    """Deprecated futures commission — QQQ uses bps via ``qqq_side_cost``."""
    del qty, per_side
    return 0.0


def mnq_fill_price(price: float, side: str, *, slip_pts: float | None = None) -> float:
    """Deprecated tick slip — maps to QQQ bps fill."""
    del slip_pts
    return qqq_fill_price(price, side)
