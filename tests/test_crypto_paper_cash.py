"""Crypto spot cash ledger — fees once, idle stable vs marks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import orbit.engine as engine


def test_paper_fill_costs_floor_fee_and_do_not_accrue_drag():
    fill = SimpleNamespace(quantity=0.15, average_price=100.0, fee=0.0)
    store: dict = {"paper_cost_drag": 0.0}

    def load():
        return dict(store)

    def update(**kw):
        store.update(kw)

    with patch.object(engine, "bot_state") as bs:
        bs.load_state.side_effect = load
        bs.update_state.side_effect = update
        fee, slip = engine._paper_fill_costs(fill)

    assert fee == 0.015  # 10 bps of 15
    assert slip == 0.0075  # 5 bps of 15
    assert store["paper_cost_drag"] == 0.0  # no second ledger


def test_bootstrap_idle_from_entry_spend_is_stable():
    book = [{
        "status": "long",
        "symbol": "SOL/USDT",
        "quantity": 0.15,
        "entry_price": 99.70,
        "paper_entry_cost": 0.03,
    }]
    store: dict = {"paper_cash_usdt": None}

    def load():
        return dict(store)

    def update(**kw):
        store.update(kw)

    with patch.object(engine, "bot_state") as bs:
        bs.load_state.side_effect = load
        bs.update_state.side_effect = update
        cash = engine._bootstrap_paper_cash(book, None, fallback_equity=99.5)
        again = engine._bootstrap_paper_cash(book, None, fallback_equity=80.0)

    expected = 100.0 - 0.15 * 99.70 - 0.03
    assert cash == expected
    assert again == expected
    assert store["paper_cash_usdt"] == expected
