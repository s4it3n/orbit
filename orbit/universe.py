"""Fixed coin universe. Do not edit after seeing backtest results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

DEFAULT_UNIVERSE: tuple[str, ...] = (
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "LINK/USDT", "AVAX/USDT", "DOGE/USDT", "LTC/USDT",
    "DOT/USDT", "ATOM/USDT", "TRX/USDT", "NEAR/USDT",
)
REGIME_SYMBOL = "BTC/USDT"
_QUOTES = ("USDT", "USDC", "FDUSD", "BUSD", "TUSD")


def normalize_symbol(raw: Any) -> str:
    text = str(raw or "").strip().upper().replace("\\", "/").replace("-", "/")
    if not text:
        return ""
    if "/" in text:
        base, _, quote = text.partition("/")
        return f"{base.strip()}/{quote.strip()}" if base.strip() and quote.strip() else ""
    for quote in _QUOTES:
        if text.endswith(quote) and len(text) > len(quote):
            return f"{text[:-len(quote)]}/{quote}"
    return ""


def parse_universe(value: Any) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_UNIVERSE
    if isinstance(value, str):
        items: Iterable[Any] = value.replace(";", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        return DEFAULT_UNIVERSE
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        symbol = normalize_symbol(item)
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
    return tuple(out) or DEFAULT_UNIVERSE


def symbols_to_fetch(universe: Sequence[str] | str | None = None) -> tuple[str, ...]:
    symbols = list(parse_universe(universe))
    if REGIME_SYMBOL not in symbols:
        symbols.append(REGIME_SYMBOL)
    return tuple(symbols)


@dataclass(frozen=True)
class EligibilityRules:
    min_history_bars: int = 210
    min_dollar_volume: float = 5_000_000.0


def check_eligibility(
    *,
    bars_available: float | None,
    dollar_volume: float | None,
    rules: EligibilityRules,
) -> tuple[bool, str | None]:
    if bars_available is None or bars_available != bars_available:
        return False, "not listed yet"
    if float(bars_available) < rules.min_history_bars:
        return False, "insufficient history"
    if dollar_volume is None or dollar_volume != dollar_volume:
        return False, "no volume data"
    if float(dollar_volume) < rules.min_dollar_volume:
        return False, "below liquidity floor"
    return True, None
