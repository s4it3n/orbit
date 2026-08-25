"""Telegram message shape — no network."""

from orbit import notify


def test_entry_message_is_short():
    text = notify.format_entry({
        "symbol": "SOL/USDT",
        "quantity": 12.4,
        "entry_price": 148.2,
        "initial_stop": 141.1,
    })
    assert "Orbit · long" in text
    assert "SOL" in text
    assert "stop" in text
    assert "Universe" not in text
    assert "Protection" not in text


def test_exit_message_shows_pnl_not_qty_spam():
    text = notify.format_exit("ETH/USDT", 0.5, 3500.0, 42.18, "trailing_stop")
    assert "Orbit · closed" in text
    assert "ETH" in text
    assert "42.18" in text
    assert "trail stop" in text


def test_take_profit_title():
    text = notify.format_exit("SOL/USDT", 6.0, 150.0, -3.2, "take_profit")
    assert "take profit" in text


def test_daily_digest():
    text = notify.format_daily(
        candle_time="2026-08-24 00:00:00+00:00",
        risk_on=True,
        held="SOL/USDT",
        top="SOL/USDT",
        equity=10120.5,
    )
    assert "Orbit · daily" in text
    assert "BTC risk-on" in text
    assert "SOL" in text
    assert "10,120.50" in text


def test_deploy_message():
    text = notify.format_deploy("abcdef123456", "main")
    assert "updated" in text
    assert "abcdef1" in text
