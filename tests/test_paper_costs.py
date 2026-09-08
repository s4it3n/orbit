"""Paper cost helpers — retail friction defaults."""

from paper.costs import (
    crypto_round_trip_drag,
    effective_crypto_fee,
    gold_fill_price,
    gold_side_cost,
    mnq_commission,
    mnq_fill_price,
)
import pytest


def test_crypto_fee_floor_beats_zero_testnet_fee():
    assert effective_crypto_fee(0.0, 1000.0) == 1.0  # 10 bps
    assert crypto_round_trip_drag(1000.0) == 1.5  # 10 bps fee + 5 bps slip


def test_gold_adverse_fill_and_cost():
    assert gold_fill_price(2000.0, "buy") > 2000.0
    assert gold_fill_price(2000.0, "sell") < 2000.0
    assert gold_side_cost(1.0, 2000.0) == 0.4  # 2 bps of 2000


def test_qqq_bps_slip_and_cost():
    from paper.costs import qqq_fill_price, qqq_side_cost

    assert qqq_fill_price(480.0, "buy") > 480.0
    assert qqq_fill_price(480.0, "sell") < 480.0
    assert qqq_side_cost(1.0, 480.0) == pytest.approx(0.048)  # 1 bps of 480
    # Legacy alias still returns a price (bps path)
    assert mnq_fill_price(480.0, "buy") > 480.0
    assert mnq_commission(2) == 0.0
