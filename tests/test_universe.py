"""Orbit universe helpers."""

from orbit.universe import (
    DEFAULT_UNIVERSE,
    REGIME_SYMBOL,
    EligibilityRules,
    check_eligibility,
    normalize_symbol,
    parse_universe,
    symbols_to_fetch,
)


def test_default_universe():
    assert REGIME_SYMBOL in DEFAULT_UNIVERSE
    assert "DOGE/USDT" in DEFAULT_UNIVERSE


def test_parse_universe():
    assert normalize_symbol("btc-usdt") == "BTC/USDT"
    assert parse_universe("BTC/USDT, eth/usdt, BTC/USDT") == ("BTC/USDT", "ETH/USDT")
    assert REGIME_SYMBOL in symbols_to_fetch(("ETH/USDT",))


def test_eligibility():
    rules = EligibilityRules(min_history_bars=210, min_dollar_volume=5_000_000)
    assert check_eligibility(bars_available=50, dollar_volume=1e9, rules=rules)[0] is False
    assert check_eligibility(bars_available=300, dollar_volume=1e9, rules=rules)[0] is True
