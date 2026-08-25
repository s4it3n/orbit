"""Passive benchmarks the rotation has to beat to be worth running.

A long-only crypto strategy that cannot outperform simply holding BTC is not
adding value, so BTC buy-and-hold is the primary reference rather than zero.
"""

from __future__ import annotations

import math
from typing import Sequence

from orbit import data


def _first_valid(prices, start: int = 0) -> int | None:
    for index in range(start, len(prices)):
        if math.isfinite(prices[index]) and prices[index] > 0:
            return index
    return None


def buy_and_hold(
    panel: "data.Panel",
    symbol: str,
    initial_capital: float,
    fee_rate: float = 0.0,
) -> dict:
    """Buy *symbol* on the first bar with a price and hold to the last bar."""
    from .metrics import equity_stats

    if symbol not in panel.symbols:
        raise ValueError(f"{symbol} is not present in the panel.")
    position = panel.index_of(symbol)
    closes = panel.data["close"][:, position]
    opens = panel.data["open"][:, position]

    start = _first_valid(closes)
    if start is None:
        raise ValueError(f"{symbol} has no usable prices in this window.")
    entry = opens[start] if math.isfinite(opens[start]) and opens[start] > 0 else closes[start]
    quantity = initial_capital * (1 - fee_rate) / entry

    curve = []
    last_price = entry
    for index in range(len(panel.dates)):
        price = closes[index]
        if math.isfinite(price) and price > 0:
            last_price = price
        equity = (
            initial_capital if index < start else quantity * last_price
        )
        curve.append({"timestamp": panel.dates[index], "equity": equity})
    # Selling at the end costs a fee too, so the comparison stays honest.
    curve[-1]["equity"] *= 1 - fee_rate

    stats = equity_stats(curve)
    stats.pop("years", None)
    stats["curve"] = curve
    return stats


def equal_weight_basket(
    panel: "data.Panel",
    symbols: Sequence[str],
    initial_capital: float,
    fee_rate: float = 0.0,
) -> dict:
    """Split capital equally across every symbol priced on the first bar, then hold.

    Coins that list later are not bought, so this measures the basket an investor
    could actually have assembled at the start of the window.
    """
    from .metrics import equity_stats

    present = [symbol for symbol in symbols if symbol in panel.symbols]
    positions = [panel.index_of(symbol) for symbol in present]
    closes = panel.data["close"]
    opens = panel.data["open"]

    investable = []
    for position in positions:
        start = _first_valid(closes[:, position])
        if start == 0:
            investable.append(position)
    if not investable:
        raise ValueError("No basket member has a price on the first bar.")

    per_asset = initial_capital / len(investable)
    quantities: dict[int, float] = {}
    for position in investable:
        entry = opens[0][position]
        if not (math.isfinite(entry) and entry > 0):
            entry = closes[0][position]
        quantities[position] = per_asset * (1 - fee_rate) / entry

    last_prices = {position: closes[0][position] for position in investable}
    curve = []
    for index in range(len(panel.dates)):
        equity = 0.0
        for position, quantity in quantities.items():
            price = closes[index][position]
            if math.isfinite(price) and price > 0:
                last_prices[position] = price
            equity += quantity * last_prices[position]
        curve.append({"timestamp": panel.dates[index], "equity": equity})
    curve[-1]["equity"] *= 1 - fee_rate

    stats = equity_stats(curve)
    stats.pop("years", None)
    stats["curve"] = curve
    return stats
