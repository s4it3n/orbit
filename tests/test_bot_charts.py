"""Chart API for Gold / MNQ desks."""

from __future__ import annotations

import pandas as pd

from webapp.bot_charts import gold_chart_payload, mnq_chart_payload


def _gold_frame(bars: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    close = pd.Series(range(bars), dtype=float) + 2000.0
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        }
    )


def _mnq_frame(bars: int = 80) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=bars, freq="15min", tz="UTC")
    close = pd.Series(range(bars), dtype=float) * 0.05 + 480.0
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": close - 0.05,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 5000.0,
        }
    )


def test_gold_chart_payload(monkeypatch):
    monkeypatch.setattr("gold_bot.data.fetch_gold_hourly", lambda force=False: _gold_frame())
    payload = gold_chart_payload(limit=60)
    assert payload["ok"] is True
    assert payload["symbol"] == "XAU/USD"
    assert len(payload["candles"]) >= 50
    assert payload["market"]["close"] is not None


def test_mnq_chart_payload(monkeypatch, tmp_path):
    monkeypatch.setattr("mnq_bot.data.fetch_mnq_15m", lambda force=False: _mnq_frame())
    monkeypatch.setattr("mnq_bot.live.ACCOUNT_PATH", tmp_path / "mnq_live.json")
    payload = mnq_chart_payload(limit=60)
    assert payload["ok"] is True
    assert payload["symbol"] == "QQQ"
    assert len(payload["candles"]) >= 50
