"""Gold/MNQ dashboard settings and market-driven MNQ rules."""

from __future__ import annotations

import pandas as pd

from gold_bot import settings as gold_settings
from gold_bot import strategy as gold_strategy
from mnq_bot import settings as mnq_settings
from mnq_bot import strategy as mnq_strategy


def test_gold_settings_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "gold_settings.json"
    monkeypatch.setattr(gold_settings, "SETTINGS_FILE", path)
    saved = gold_settings.save_settings(
        {"donchian_period": 18, "risk_pct": 0.012, "bot_enabled": True}
    )
    assert saved["donchian_period"] == 18
    assert saved["risk_pct"] == 0.012
    rules = gold_settings.rules_from_settings()
    assert rules.donchian_period == 18
    assert rules.risk_pct == 0.012


def test_mnq_settings_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "mnq_settings.json"
    monkeypatch.setattr(mnq_settings, "SETTINGS_FILE", path)
    saved = mnq_settings.save_settings(
        {"breakout_atr_mult": 0.1, "risk_pct": 0.008, "max_risk_pct": 0.12}
    )
    rules = mnq_settings.rules_from_settings(saved)
    assert rules.breakout_atr_mult == 0.1
    assert rules.risk_pct == 0.008
    assert rules.max_risk_pct == 0.12


def test_mnq_breakout_buffer_uses_atr():
    rules = mnq_strategy.MnqRules(breakout_points=2.0, breakout_atr_mult=0.1)
    assert mnq_strategy._breakout_buffer(rules, 50.0) == 5.0
    assert mnq_strategy._breakout_buffer(rules, 10.0) == 2.0


def test_mnq_require_close_break_uses_high_low():
    rules = mnq_strategy.MnqRules(require_close_break=False, volume_mult=0.0)
    row = {
        "cet_hour": 16,
        "cet_minute": 0,
        "close": 480.6,
        "high": 481.0,
        "low": 479.0,
        "volume": 1000.0,
        "volume_sma": 500.0,
        "atr": 0.8,
    }
    signal = mnq_strategy.evaluate_entry(
        row, or_high=480.5, or_low=479.5, trades_today=0, rules=rules
    )
    assert signal is not None
    assert signal.side == "long"


def test_mnq_size_contracts_reads_rules_risk():
    rules = mnq_strategy.MnqRules(risk_pct=0.01, max_risk_pct=0.15)
    qty, _ = mnq_strategy.size_contracts(10_000.0, 5.0, entry=480.0, rules=rules)
    qty_default, _ = mnq_strategy.size_contracts(10_000.0, 5.0, entry=480.0)
    assert qty > qty_default


def test_gold_rules_from_settings_session_hours(tmp_path, monkeypatch):
    path = tmp_path / "gold_settings.json"
    monkeypatch.setattr(gold_settings, "SETTINGS_FILE", path)
    gold_settings.save_settings({"session_start_hour": 8, "session_end_hour": 16})
    rules = gold_settings.rules_from_settings()
    assert rules.session_start_hour == 8
    assert rules.session_end_hour == 16
