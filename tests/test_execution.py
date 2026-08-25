"""Execution helpers."""

from orbit.execution import client_order_id, normalize_quantity


class FakeExchange:
    def load_markets(self):
        return None

    def market(self, symbol):
        return {"limits": {"amount": {"min": 0.0001}, "cost": {"min": 10}}}

    def amount_to_precision(self, symbol, quantity):
        return f"{quantity:.8f}"


def test_normalize_and_client_id():
    ex = FakeExchange()
    assert normalize_quantity(ex, "BTC/USDT", 1.0, 100.0, available_quote=50) > 0
    assert normalize_quantity(ex, "BTC/USDT", 0.00001, 100.0) == 0.0
    assert client_order_id("BTC/USDT", "ts", "entry").startswith("orbit-")
