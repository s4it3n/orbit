"""Orbit strategy rules."""

from orbit.strategy import (
    AssetSnapshot,
    RotationRules,
    allocation_fraction,
    evaluate_candidates,
    evaluate_regime,
    exit_reason,
    fill_open_slots,
    initial_stop_price,
    market_regime,
    position_size,
    select_target,
    select_targets,
    take_profit_price,
    update_trailing_stop,
)
from orbit.universe import EligibilityRules


def _snap(**kwargs) -> AssetSnapshot:
    base = dict(
        symbol="BTC/USDT", close=100.0, trend_ema=90.0, fast_ema=95.0,
        breadth_ema=97.0, rsi=55.0, momentum=0.2, volatility=0.3, score=0.66,
        atr=2.0, roc_14=0.20, dollar_volume=1e9, bars_available=900.0,
    )
    base.update(kwargs)
    return AssetSnapshot(**base)


def test_regime_and_ranking():
    assert market_regime(_snap(close=100, trend_ema=90))[0] is True
    assert market_regime(_snap(close=80, trend_ema=90))[0] is False
    rules = RotationRules(eligibility=EligibilityRules(100, 1e6))
    cands = evaluate_candidates([
        _snap(symbol="BTC/USDT", score=0.66),
        _snap(symbol="SOL/USDT", momentum=0.6, volatility=1.2, score=0.5),
    ], rules)
    assert select_target(cands).symbol == "BTC/USDT"


def test_fast_regime_blocks_new_only():
    on = evaluate_regime(
        _snap(close=100, trend_ema=90, fast_ema=95, rsi=60),
        RotationRules(max_positions=3),
    )
    assert on.macro_on is True and on.allow_new is True
    assert on.max_open_slots == 3 and on.reason == "risk-on"
    below_fast = evaluate_regime(_snap(close=100, trend_ema=90, fast_ema=110, rsi=60))
    assert below_fast.macro_on is True and below_fast.allow_new is False
    assert below_fast.max_open_slots == 0
    weak_rsi = evaluate_regime(_snap(close=100, trend_ema=90, fast_ema=95, rsi=40))
    assert weak_rsi.macro_on is True and weak_rsi.allow_new is False
    risk_off = evaluate_regime(_snap(close=80, trend_ema=90, fast_ema=70, rsi=30))
    assert risk_off.macro_on is False and risk_off.allow_new is False
    delayed = RotationRules(macro_confirm_bars=2)
    first_break = evaluate_regime(
        _snap(close=80, trend_ema=90, fast_ema=70, rsi=30),
        delayed,
        previous=_snap(close=100, trend_ema=90, fast_ema=95, rsi=60),
    )
    assert first_break.macro_on is True and first_break.allow_new is False
    assert first_break.reason == "macro-unconfirmed"
    second_break = evaluate_regime(
        _snap(close=80, trend_ema=90, fast_ema=70, rsi=30),
        delayed,
        previous=_snap(close=85, trend_ema=90, fast_ema=70, rsi=30),
    )
    assert second_break.macro_on is False
    below_short = evaluate_regime(_snap(breadth_ema=105.0))
    assert below_short.macro_on is True and below_short.allow_new is False
    assert below_short.reason == "chop"
    flat_roc = evaluate_regime(_snap(roc_14=-0.01))
    assert flat_roc.allow_new is False and flat_roc.reason == "chop"
    warming = evaluate_regime(_snap(breadth_ema=float("nan")))
    assert warming.allow_new is False and warming.reason == "chop"
    from orbit.strategy import entry_rules
    rules = RotationRules(max_allocation_pct=0.30, max_portfolio_exposure=0.90)
    sized = entry_rules(rules, heat_active=False, defensive=True)
    assert sized.max_allocation_pct == 0.30
    assert sized.max_portfolio_exposure == 0.90
    single = entry_rules(rules, heat_active=False, max_open_slots=1)
    assert single.max_positions == 1 and single.max_allocation_pct == 0.30


def test_hysteresis_and_sizing():
    rules = RotationRules(rank_buffer=2, min_hold_days=5, max_positions=3)
    cands = evaluate_candidates([
        _snap(symbol="AAA/USDT", score=1.0),
        _snap(symbol="BBB/USDT", score=0.9),
        _snap(symbol="CCC/USDT", score=0.1),
    ], rules)
    assert [item.symbol for item in select_targets(cands, rules)] == [
        "AAA/USDT", "BBB/USDT", "CCC/USDT",
    ]
    assert fill_open_slots(cands, ["AAA/USDT"], rules)[0].symbol == "BBB/USDT"
    assert exit_reason("CCC/USDT", cands, risk_on=True, bars_held=2, rules=rules) is None
    # Rank drop alone is not enough: the challenger must clear the ROC band.
    assert exit_reason("CCC/USDT", cands, risk_on=True, bars_held=10, rules=rules) is None
    assert allocation_fraction(0.3, RotationRules(target_volatility=0.6, max_allocation_pct=0.30)) == 0.30
    assert position_size(10_000, 100, 0.3, RotationRules(target_volatility=0.6, max_allocation_pct=0.30)) == 30.0
    assert initial_stop_price(100, 2, 1.5) == 97.0
    assert take_profit_price(100, 2, 2.0) == 104.0
    stop, high = update_trailing_stop(95.0, 100.0, 60.0, 2.0, 4.0)
    assert stop == 95.0 and high == 100.0


def test_rotation_hysteresis_needs_roc_edge():
    rules = RotationRules(rank_buffer=2, min_hold_days=5, max_positions=3)
    held = ["CCC/USDT"]
    thin = evaluate_candidates([
        _snap(symbol="AAA/USDT", score=1.0, roc_14=0.24),
        _snap(symbol="BBB/USDT", score=0.9, roc_14=0.22),
        _snap(symbol="CCC/USDT", score=0.1, roc_14=0.20),
    ], rules)
    assert exit_reason(
        "CCC/USDT", thin, risk_on=True, bars_held=10, rules=rules,
        held_symbols=held,
    ) is None
    wide = evaluate_candidates([
        _snap(symbol="AAA/USDT", score=1.0, roc_14=0.26),
        _snap(symbol="BBB/USDT", score=0.9, roc_14=0.22),
        _snap(symbol="CCC/USDT", score=0.1, roc_14=0.20),
    ], rules)
    assert exit_reason(
        "CCC/USDT", wide, risk_on=True, bars_held=10, rules=rules,
        held_symbols=held,
    ) == "rank_drop"
    # A challenger that is already held cannot justify the rotation.
    assert exit_reason(
        "CCC/USDT", wide, risk_on=True, bars_held=10, rules=rules,
        held_symbols=["AAA/USDT", "BBB/USDT", "CCC/USDT"],
    ) is None
