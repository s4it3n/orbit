"""Live paper loop tests for Gold and MNQ (no Yahoo network)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from gold_bot import live as gold_live
from gold_bot import strategy as gold_strategy
from mnq_bot import live as mnq_live
from mnq_bot import strategy as mnq_strategy
from paper import loops


def _gold_frame(bars: int = 220) -> pd.DataFrame:
    stamps = pd.date_range("2024-01-01", periods=bars, freq="1h", tz="UTC")
    close = 2300.0 + np.linspace(0, 40, bars) + np.sin(np.linspace(0, 20, bars))
    close[150:170] = close[149]
    close[170] = close[169] + 22
    return pd.DataFrame({
        "timestamp": stamps,
        "open": np.roll(close, 1),
        "high": close + 1.5,
        "low": close - 1.5,
        "close": close,
        "volume": np.full(bars, 1000.0),
    })


def _mnq_frame() -> pd.DataFrame:
    stamps = pd.date_range("2024-06-03 06:00", periods=26 * 8, freq="15min", tz="UTC")
    px = 20_000.0
    rows = []
    for ts in stamps:
        cet = ts.tz_convert(mnq_strategy.CET)
        shock = 8.0 if cet.hour == 15 and cet.minute == 45 else 0.4
        close = px + shock
        rows.append({
            "timestamp": ts,
            "open": px,
            "high": max(px, close) + 2,
            "low": min(px, close) - 2,
            "close": close,
            "volume": 1800 if cet.hour == 15 and cet.minute >= 45 else 700,
        })
        px = close
    return pd.DataFrame(rows)


def test_gold_live_iteration_writes_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gold_live, "ACCOUNT_PATH", tmp_path / "gold_live.json")
    monkeypatch.setattr(gold_live, "STATE_PATH", tmp_path / "gold_state.json")
    monkeypatch.setattr(gold_live, "fetch_gold_hourly", lambda force=False: _gold_frame())
    payload = gold_live.run_iteration(force_refresh=False)
    assert payload["bot_id"] == "gold"
    assert payload["mode"] == "paper_live"
    assert payload["status"] in {"ACTIVE", "PAPER"}
    assert (tmp_path / "gold_state.json").exists()
    account = json.loads((tmp_path / "gold_live.json").read_text(encoding="utf-8"))
    assert account["last_processed_bar_ts"]
    assert account["equity_curve"]


def test_mnq_live_iteration_writes_state(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mnq_live, "ACCOUNT_PATH", tmp_path / "mnq_live.json")
    monkeypatch.setattr(mnq_live, "STATE_PATH", tmp_path / "mnq_state.json")
    monkeypatch.setattr(mnq_live, "fetch_mnq_15m", lambda force=False: _mnq_frame())
    payload = mnq_live.run_iteration(force_refresh=False)
    assert payload["bot_id"] == "mnq"
    assert payload["mode"] == "paper_live"
    assert (tmp_path / "mnq_state.json").exists()
    account = json.loads((tmp_path / "mnq_live.json").read_text(encoding="utf-8"))
    assert account["last_processed_bar_ts"]


def test_paper_loops_start_stop():
    started = threading.Event()
    stopped = threading.Event()

    def loop(stop_event: threading.Event) -> None:
        started.set()
        while not stop_event.wait(0.05):
            pass
        stopped.set()

    assert loops.start("testbot", loop)["ok"]
    assert started.wait(2)
    assert loops.is_running("testbot")
    assert loops.stop("testbot")["ok"]
    assert stopped.wait(2)
    assert not loops.is_running("testbot")


def test_gold_process_can_open_from_signal():
    account = {
        "cash": 100_000.0,
        "position": None,
        "trades": [],
        "equity_curve": [],
        "logs": [],
    }
    row = {
        "timestamp": pd.Timestamp("2024-06-01 14:00", tz="UTC"),
        "high": 2401.0,
        "low": 2390.0,
        "close": 2400.0,
        "donchian_high": 2380.0,
        "donchian_low": 2350.0,
        "atr": 10.0,
        "atr_sma": 20.0,
        "squeeze": True,
        "squeeze_bars": 2.0,
        "atr_pct": 10 / 2400,
        "prev_close": 2380.0,
        "ny_hour": 10,
        "trend_sma": float("nan"),
    }
    gold_live._process_bar(account, row, gold_strategy.GoldRules())
    assert account["position"] is not None
    assert account["position"]["side"] == "long"
