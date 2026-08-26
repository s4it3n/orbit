"""Telegram message shape — no network."""

from orbit import notify


def test_entry_message_is_short():
    text = notify.format_entry({
        "symbol": "SOL/USDT",
        "quantity": 12.4,
        "entry_price": 148.2,
        "initial_stop": 141.1,
    }, equity=1000.0)
    assert "Crypto · buy" in text
    assert "SOL" in text
    assert "stop" in text
    assert "equity  1,000.00 USDT" in text
    assert "Universe" not in text
    assert "Protection" not in text


def test_exit_message_shows_pnl_and_equity():
    text = notify.format_exit(
        "ETH/USDT", 0.5, 3500.0, 42.18, "trailing_stop", equity=1042.18
    )
    assert "Crypto · sell" in text
    assert "ETH" in text
    assert "42.18" in text
    assert "trail stop" in text
    assert "equity  1,042.18 USDT" in text


def test_take_profit_title():
    text = notify.format_exit("SOL/USDT", 6.0, 150.0, -3.2, "take_profit", equity=996.8)
    assert "take profit" in text
    assert "equity" in text


def test_paper_equity_never_shows_faucet():
    assert notify.paper_equity(10000.0) == notify.config.ORBIT_PAPER_EQUITY
    text = notify.format_startup(10000.0)
    assert "10,000" not in text
    assert "1,000.00" in text or f"{notify.config.ORBIT_PAPER_EQUITY:,.2f}" in text


def test_daily_digest_caps_equity():
    text = notify.format_daily(
        candle_time="2026-08-24 00:00:00+00:00",
        risk_on=True,
        held="SOL/USDT",
        top="SOL/USDT",
        equity=10120.5,
    )
    assert "Crypto · daily" in text
    assert "BTC risk-on" in text
    assert "SOL" in text
    assert "10,120.50" not in text
    assert "1,000.00" in text or f"{notify.config.ORBIT_PAPER_EQUITY:,.2f}" in text


def test_notify_daily_is_silent():
    # Should not raise / should not attempt send when called.
    notify.notify_daily(
        candle_time="2026-08-24",
        risk_on=True,
        held=None,
        top=None,
        equity=10000,
    )


def test_gold_exit_includes_bot_and_equity():
    text = notify.format_paper_exit(
        notify.GOLD_BOT,
        side="long",
        symbol="XAU/USD",
        qty=0.1,
        price=2650.0,
        pnl=12.5,
        reason="stop",
        equity=1012.5,
    )
    assert "Gold · closed" in text
    assert "equity  1,012.50 USDT" in text


def test_deploy_message():
    text = notify.format_deploy("abcdef123456", "main")
    assert "updated" in text
    assert "abcdef1" in text
