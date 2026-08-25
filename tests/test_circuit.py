"""Portfolio heat, BTC blow-off, and 5-day market-shock circuit breakers."""

from orbit.strategy import (
    AssetSnapshot,
    EquityLock,
    HeatState,
    RotationRules,
    allocation_fraction,
    book_adjustments,
    btc_lock_reclaim,
    decay_stop_pause,
    entry_rules,
    evaluate_regime,
    is_blowoff,
    lookback_return,
    select_new_entries,
    start_stop_pause,
    trail_multiple,
    update_equity_lock,
    update_heat,
    update_market_shock,
    update_trailing_stop,
)
from orbit.universe import EligibilityRules

from orbit import data
from backtest.engine import run_backtest
from tests.test_backtest_engine import _cfg, _frame


def _snap(**kwargs) -> AssetSnapshot:
    base = dict(
        symbol="ETH/USDT", close=100.0, trend_ema=90.0, fast_ema=95.0,
        breadth_ema=97.0, rsi=55.0, momentum=0.2, volatility=0.3, score=0.66,
        atr=2.0, roc_14=0.20, dollar_volume=1e9, bars_available=900.0,
    )
    base.update(kwargs)
    return AssetSnapshot(**base)


def _rules(**kwargs) -> RotationRules:
    base = dict(
        max_positions=3,
        heat_max_positions=1,
        heat_size_mult=0.50,
        max_allocation_pct=0.30,
        target_volatility=0.60,
        eligibility=EligibilityRules(100, 1e6),
    )
    base.update(kwargs)
    return RotationRules(**base)


def test_heat_hysteresis_and_half_size():
    rules = _rules()
    heat = HeatState(peak_equity=10_000.0)
    heat = update_heat(heat, 9_100.0, in_market=True, rules=rules)
    assert heat.active is False
    heat = update_heat(heat, 9_000.0, in_market=True, rules=rules)
    assert heat.active is True and heat.drawdown >= 0.10
    heat = update_heat(heat, 9_500.0, in_market=True, rules=rules)
    assert heat.active is True
    heat = update_heat(heat, 9_600.0, in_market=True, rules=rules)
    assert heat.active is False
    sized = entry_rules(rules, heat_active=True)
    assert sized.max_allocation_pct == 0.15
    assert sized.max_positions == 1
    assert allocation_fraction(0.3, sized) == 0.15


def test_heat_freezes_peak_when_flat():
    rules = _rules()
    heat = update_heat(HeatState(peak_equity=10_000.0), 12_000.0, in_market=False, rules=rules)
    assert heat.peak_equity == 10_000.0
    heat = update_heat(heat, 12_000.0, in_market=True, rules=rules)
    assert heat.peak_equity == 12_000.0


def test_blowoff_blocks_alts_not_btc():
    rules = _rules()
    btc = _snap(symbol="BTC/USDT", rsi=80.0, score=1.0)
    eth = _snap(symbol="ETH/USDT", score=0.9)
    assert is_blowoff(_snap(symbol="BTC/USDT", rsi=80.0), rules) is True
    assert is_blowoff(_snap(symbol="BTC/USDT", close=140.0, fast_ema=100.0, rsi=50.0), rules) is True
    assert is_blowoff(_snap(symbol="BTC/USDT", rsi=60.0, close=100.0, fast_ema=95.0), rules) is False
    from orbit.strategy import evaluate_candidates
    cands = evaluate_candidates([btc, eth], rules)
    picks, reason = select_new_entries(
        cands, [], rules, allow_new=True, blowoff=True, market_shock=False,
        heat_active=False, cooldown=False, daily_loss_guard=False,
        regime_symbol="BTC/USDT",
    )
    assert reason is None
    assert [item.symbol for item in picks] == ["BTC/USDT"]
    picks, reason = select_new_entries(
        cands, ["BTC/USDT"], rules, allow_new=True, blowoff=True, market_shock=False,
        heat_active=False, cooldown=False, daily_loss_guard=False,
        regime_symbol="BTC/USDT",
    )
    assert picks == [] and reason == "blow-off"


def test_shock_latches_until_positive_return():
    rules = _rules()
    assert round(lookback_return(92.0, 100.0), 10) == -0.08
    assert update_market_shock(False, -0.07, rules) is False
    assert update_market_shock(False, -0.09, rules) is True
    assert update_market_shock(True, -0.03, rules) is True
    assert update_market_shock(True, 0.01, rules) is False
    picks, reason = select_new_entries(
        [], [], rules, allow_new=True, blowoff=False, market_shock=True,
        heat_active=False, cooldown=False, daily_loss_guard=False,
        regime_symbol="BTC/USDT",
    )
    assert picks == [] and reason == "market shock"
    assert trail_multiple(rules, market_shock=True) == rules.trail_atr_mult
    tight, _ = update_trailing_stop(95.0, 100.0, 100.0, 2.0, 1.0)
    wide, _ = update_trailing_stop(95.0, 100.0, 100.0, 2.0, 2.0)
    assert tight > wide


def test_heat_keeps_best_lot_and_scales():
    rules = _rules()
    adj = book_adjustments(
        [
            ("AAA/USDT", 3_000.0, 200.0),
            ("BBB/USDT", 3_000.0, -400.0),
            ("CCC/USDT", 3_000.0, 50.0),
        ],
        equity=10_000.0,
        heat_active=True,
        defensive=False,
        rules=rules,
    )
    assert set(adj.exit_symbols) == {"BBB/USDT", "CCC/USDT"}
    assert adj.reductions and adj.reductions[0][0] == "AAA/USDT"
    assert abs(adj.reductions[0][1] - 0.5) < 1e-9
    assert adj.reductions[0][2] == "heat_scale"


def test_equity_lock_flattens_until_btc_reclaims():
    rules = _rules(equity_lock_pct=0.15, lock_reclaim_rsi=55.0)
    lock = EquityLock(all_time_peak=10_000.0, lock_peak=10_000.0)
    lock = update_equity_lock(lock, 8_600.0, reclaim=False, rules=rules)
    assert lock.active is False
    lock = update_equity_lock(lock, 8_500.0, reclaim=False, rules=rules)
    assert lock.active is True and lock.drawdown >= 0.15
    weak = _snap(symbol="BTC/USDT", close=100.0, fast_ema=95.0, rsi=52.0)
    assert btc_lock_reclaim(weak, rules) is False
    lock = update_equity_lock(lock, 8_500.0, reclaim=False, rules=rules)
    assert lock.active is True
    strong = _snap(symbol="BTC/USDT", close=100.0, fast_ema=90.0, rsi=60.0)
    assert btc_lock_reclaim(strong, rules) is True
    lock = update_equity_lock(lock, 8_500.0, reclaim=True, rules=rules)
    assert lock.active is False
    assert lock.lock_peak == 8_500.0
    picks, reason = select_new_entries(
        [], [], rules, allow_new=True, blowoff=False, market_shock=False,
        heat_active=False, cooldown=False, daily_loss_guard=False,
        regime_symbol="BTC/USDT", equity_lock=True,
    )
    assert picks == [] and reason == "equity lock"


def test_heat_blocks_extra_slots():
    rules = _rules()
    from orbit.strategy import evaluate_candidates
    cands = evaluate_candidates([
        _snap(symbol="AAA/USDT", score=1.0),
        _snap(symbol="BBB/USDT", score=0.9),
        _snap(symbol="CCC/USDT", score=0.8),
    ], rules)
    picks, reason = select_new_entries(
        cands, ["AAA/USDT"], rules, allow_new=True, blowoff=False,
        market_shock=False, heat_active=True, cooldown=False,
        daily_loss_guard=False, regime_symbol="BTC/USDT",
    )
    assert picks == [] and reason == "risk mitigation"
    picks, reason = select_new_entries(
        cands, [], rules, allow_new=True, blowoff=False,
        market_shock=False, heat_active=True, cooldown=False,
        daily_loss_guard=False, regime_symbol="BTC/USDT",
    )
    assert [item.symbol for item in picks] == ["AAA/USDT"]


def test_drift_defense_caps_slot_one():
    rules = _rules()
    from orbit.strategy import evaluate_candidates, entry_rules, is_btc_drift
    assert is_btc_drift(-0.04, rules) is True
    assert is_btc_drift(0.0, rules) is False
    assert is_btc_drift(-0.09, rules) is False
    cands = evaluate_candidates([
        _snap(symbol="AAA/USDT", score=1.0),
        _snap(symbol="BBB/USDT", score=0.9),
        _snap(symbol="CCC/USDT", score=0.8),
    ], rules)
    sized = entry_rules(rules, heat_active=False, drift_active=True)
    assert sized.max_positions == 1
    assert sized.max_allocation_pct == 0.15
    picks, reason = select_new_entries(
        cands, [], rules, allow_new=True, blowoff=False, market_shock=False,
        heat_active=False, cooldown=False, daily_loss_guard=False,
        regime_symbol="BTC/USDT", btc_5d_return=-0.04,
    )
    assert [item.symbol for item in picks] == ["AAA/USDT"]
    picks, reason = select_new_entries(
        cands, ["AAA/USDT"], rules, allow_new=True, blowoff=False,
        market_shock=False, heat_active=False, cooldown=False,
        daily_loss_guard=False, regime_symbol="BTC/USDT", btc_5d_return=-0.04,
    )
    assert picks == [] and reason == "drift defense"
    picks, reason = select_new_entries(
        cands, ["AAA/USDT"], rules, allow_new=True, blowoff=False,
        market_shock=False, heat_active=False, cooldown=False,
        daily_loss_guard=False, regime_symbol="BTC/USDT", btc_5d_return=0.01,
    )
    assert [item.symbol for item in picks] == ["BBB/USDT", "CCC/USDT"]


def test_stop_pause_and_late_cycle():
    rules = _rules(stop_pause_bars=5, late_cycle_buffer=0.04, regime_confirm_bars=2)
    from orbit.strategy import evaluate_candidates
    cands = evaluate_candidates([
        _snap(symbol="AAA/USDT", score=1.0),
        _snap(symbol="BBB/USDT", score=0.9),
    ], rules)
    kwargs = dict(
        allow_new=True, blowoff=False, market_shock=False, heat_active=False,
        cooldown=False, daily_loss_guard=False, regime_symbol="BTC/USDT",
    )
    picks, reason = select_new_entries(cands, [], rules, stop_pause=True, **kwargs)
    assert picks == [] and reason == "stop pause"
    assert start_stop_pause("initial_stop", rules) == 5
    assert start_stop_pause("trailing_stop", rules) == 0
    assert decay_stop_pause(1) == 0

    unlocked = _snap(close=100, trend_ema=90, fast_ema=95, breadth_ema=97, rsi=60, roc_14=0.05)
    first = evaluate_regime(unlocked, rules, previous=None)
    assert first.allow_new is False and first.reason == "unconfirmed"
    second = evaluate_regime(unlocked, rules, previous=unlocked)
    assert second.allow_new is True
    late = evaluate_regime(
        _snap(close=100, trend_ema=99, fast_ema=95, breadth_ema=97, rsi=60, roc_14=0.05),
        rules,
        previous=unlocked,
    )
    assert late.allow_new is False and late.reason == "late-cycle"


def test_backtest_blowoff_skips_alts():
    # Sit in cash below BTC's trend EMA, then gap up into a blow-off so the
    # next bar tries to buy alts and is refused.
    btc = _frame([50.0] * 70 + [120.0, 125.0, 130.0])
    n = 73
    aaa = _frame([20 + i * 0.4 for i in range(n)])
    bbb = _frame([10 + i * 0.3 for i in range(n)])
    panel = data.align_panel({"BTC/USDT": btc, "AAA/USDT": aaa, "BBB/USDT": bbb})
    result = run_backtest(panel, _cfg(
        universe=("AAA/USDT", "BBB/USDT"),
        max_positions=3,
        blowoff_ema_extension=0.20,
        blowoff_rsi=99.0,
        trail_atr_mult=50.0,
        atr_sl_mult=50.0,
        take_profit_atr_mult=50.0,
    ))
    assert result.skipped_signals.get("blow-off", 0) > 0
