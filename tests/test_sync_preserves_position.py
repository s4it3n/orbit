"""Regression: failed Binance fetch must not wipe open lots."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import orbit.engine as engine


def test_sync_state_without_book_preserves_open_lot():
    open_lot = {
        "status": "long",
        "symbol": "SOL/USDT",
        "quantity": 0.15,
        "entry_price": 99.7,
        "paper_entry_cost": 0.02,
    }
    store = {
        "positions": [open_lot],
        "position": open_lot,
        "paper_cash_usdt": 85.02,
        "cash_usdt": 85.02,
        "equity_usdt": 99.9,
        "exchange_equity_anchor": 10000.0,
    }

    def load():
        return dict(store)

    def update(**kw):
        store.update(kw)

    guard = MagicMock()
    guard.start_balance = 100.0
    guard.trading_paused = False

    with patch.object(engine, "bot_state") as bs:
        bs.load_state.side_effect = load
        bs.update_state.side_effect = update
        # Mimic the error-path call: no snapshot / book / position.
        engine._sync_state(guard)

    assert store["positions"] and store["positions"][0]["symbol"] == "SOL/USDT"
    assert store["position"]["status"] == "long"
    assert store["paper_cash_usdt"] == 85.02
    assert store["cash_usdt"] == 85.02
