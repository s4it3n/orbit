"""Telegram message shape — no network."""

from orbit import notify


def test_entry_message_is_short():
    text = notify.format_entry({
        "symbol": "SOL/USDT",
        "quantity": 12.4,
        "entry_price": 148.2,
        "initial_stop": 141.1,
    }, equity=100.0)
    assert "Crypto · buy" in text
    assert "SOL" in text
    assert "stop" in text
    assert "Crypto  100.00" in text
    assert "desk" in text
    assert "Universe" not in text
    assert "Protection" not in text


def test_exit_message_shows_pnl_and_desk():
    text = notify.format_exit(
        "ETH/USDT",
        0.5,
        3500.0,
        4.22,
        "trailing_stop",
        equity=104.22,
    )
    assert "Crypto · sell" in text
    assert "ETH" in text
    assert "4.22" in text
    assert "trail stop" in text
    assert "Crypto  104.22" in text
    assert "Gold" in text
    assert "QQQ" in text
    assert "desk" in text


def test_take_profit_title():
    text = notify.format_exit("SOL/USDT", 6.0, 150.0, -0.32, "take_profit", equity=99.68)
    assert "take profit" in text
    assert "desk" in text


def test_paper_equity_never_shows_faucet():
    assert notify.paper_equity(10000.0) == notify.config.ORBIT_PAPER_EQUITY
    text = notify.format_startup(10000.0)
    assert "10,000" not in text
    assert "Orbit · online" in text
    assert "desk" in text


def test_desk_block_totals_three_books():
    text = notify.format_desk_block(
        {
            notify.CRYPTO_BOT: 100.0,
            notify.GOLD_BOT: 110.0,
            notify.MNQ_BOT: 90.0,
        }
    )
    assert "Crypto  100.00" in text
    assert "Gold    110.00" in text
    assert "QQQ     90.00" in text
    assert "desk    300.00" in text
    assert "(+0.00)" in text or "(−0.00)" in text or "(+0.00)" in text


def test_desk_block_shows_profit():
    text = notify.format_desk_block(
        {
            notify.CRYPTO_BOT: 110.0,
            notify.GOLD_BOT: 100.0,
            notify.MNQ_BOT: 100.0,
        }
    )
    assert "desk    310.00" in text
    assert "+10.00" in text


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


def test_desk_daily_summarizes_books_and_trades():
    text = notify.format_desk_daily(
        day="2026-08-30",
        books={
            notify.CRYPTO_BOT: 162.0,
            notify.GOLD_BOT: 99.0,
            notify.MNQ_BOT: 100.0,
        },
        open_books={
            notify.CRYPTO_BOT: 150.0,
            notify.GOLD_BOT: 100.0,
            notify.MNQ_BOT: 100.0,
        },
        trades=[
            {"bot": notify.GOLD_BOT, "symbol": "XAU/USD", "pnl": 1.25, "reason": "stop"},
            {"bot": notify.CRYPTO_BOT, "symbol": "SOL", "pnl": -0.40, "reason": "exit"},
        ],
        positions=["Crypto  long SOL"],
        regime="BTC risk-on",
    )
    assert "Orbit · daily" in text
    assert "2026-08-30 UTC" in text
    assert "desk" in text
    assert "day" in text
    assert "2 closed" in text
    assert "1W/1L" in text
    assert "Crypto  long SOL" in text
    assert "BTC risk-on" in text


def test_notify_daily_is_safe_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(notify, "_DAILY_PATH", tmp_path / "desk_daily.json")
    monkeypatch.setattr(notify, "TELEGRAM_DAILY_HOUR", 0)
    monkeypatch.setattr(notify, "is_configured", lambda: True)
    monkeypatch.setattr(notify, "send", lambda message: True)
    monkeypatch.setattr(
        notify,
        "desk_books",
        lambda **kwargs: {
            notify.CRYPTO_BOT: 100.0,
            notify.GOLD_BOT: 100.0,
            notify.MNQ_BOT: 100.0,
        },
    )
    monkeypatch.setattr(notify, "_trades_closed_on", lambda day: [])
    monkeypatch.setattr(notify, "_open_positions", lambda: [])
    monkeypatch.setattr(notify, "_crypto_regime_line", lambda: "BTC risk-on")
    assert notify.maybe_notify_daily_desk() is True
    assert notify.maybe_notify_daily_desk() is False  # once per day


def test_gold_exit_includes_bot_and_desk():
    text = notify.format_paper_exit(
        notify.GOLD_BOT,
        side="long",
        symbol="XAU/USD",
        qty=0.1,
        price=2650.0,
        pnl=12.5,
        reason="stop",
        equity=101.25,
    )
    assert "Gold · closed" in text
    assert "Gold    101.25" in text
    assert "desk" in text


def test_deploy_message():
    text = notify.format_deploy("abcdef123456", "main")
    assert "updated" in text
    assert "abcdef1" in text
