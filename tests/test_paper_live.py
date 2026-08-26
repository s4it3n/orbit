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
from orbit import exporter as orbit_exporter
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
    assert float(account["initial_capital"]) == gold_live.INITIAL_CAPITAL
    assert gold_live.INITIAL_CAPITAL == 1000.0


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
    assert float(account["initial_capital"]) == mnq_live.INITIAL_CAPITAL


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
        "cash": 1000.0,
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


def test_gold_resets_stale_100k_account(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gold_live, "ACCOUNT_PATH", tmp_path / "gold_live.json")
    path = tmp_path / "gold_live.json"
    path.write_text(
        json.dumps({
            "bot_id": "gold",
            "initial_capital": 100_000.0,
            "cash": 99_000.0,
            "trades": [{"pnl_usdt": 1.0}],
            "position": {"side": "long"},
            "equity_curve": [{"timestamp": "x", "equity": 100_000}],
            "logs": [],
        }),
        encoding="utf-8",
    )
    account = gold_live._load()
    assert account["initial_capital"] == 1000.0
    assert account["cash"] == 1000.0
    assert account["trades"] == []
    assert account["position"] is None
    assert any("Reset paper account to $1000" in (row.get("message") or "") for row in account["logs"])


def test_mnq_qty_floor_forces_one_lot_on_1k():
    # 0.5% of $1000 cannot buy 1 lot, but 1-lot risk ($10) ≤ 10% of cash → force qty=1
    qty, forced = mnq_strategy.size_contracts(1000.0, risk_pts=5.0, point_value=2.0)
    assert qty == 1
    assert forced is True
    # Typical OR stop (~20 pts = $40) still allowed on $1k paper (≤10%)
    qty_mid, forced_mid = mnq_strategy.size_contracts(1000.0, risk_pts=20.0, point_value=2.0)
    assert qty_mid == 1
    assert forced_mid is True
    # Too wide: 1-lot risk $120 > 10% of $1000 → stay flat
    qty2, forced2 = mnq_strategy.size_contracts(1000.0, risk_pts=60.0, point_value=2.0)
    assert qty2 == 0
    assert forced2 is False
    # Larger cash sizes normally without force
    qty3, forced3 = mnq_strategy.size_contracts(50_000.0, risk_pts=5.0, point_value=2.0)
    assert qty3 >= 1
    assert forced3 is False


def test_mnq_process_opens_with_forced_qty(tmp_path: Path):
    # OR width ≥8; stop at mid → risk_pts≈7 → $14 ≤ 2% of $1k so qty floors to 1
    account = {
        "cash": 1000.0,
        "position": None,
        "trades": [],
        "equity_curve": [],
        "logs": [],
        "or_high": 2008.0,
        "or_low": 2000.0,
        "trades_today": 0,
        "current_day": "2024-06-03",
    }
    row = {
        "timestamp": pd.Timestamp("2024-06-03 14:00", tz="UTC"),
        "cet_date": "2024-06-03",
        "open": 2009.0,
        "high": 2014.0,
        "low": 2008.0,
        "close": 2011.0,
        "volume": 2000.0,
        "volume_sma": 1000.0,
        "cet_hour": 16,
        "cet_minute": 0,
        "atr": 12.0,
    }
    mnq_live._process_bar(account, row, mnq_strategy.MnqRules())
    assert account["position"] is not None
    assert account["position"]["qty"] == 1
    assert any("Forced MNQ qty=1" in (log.get("message") or "") for log in account["logs"])


def test_exporter_live_trade_count_not_accepted_153(monkeypatch):
    live = {
        "bot_running": True,
        "trading_paused": False,
        "equity_usdt": 1000.0,
        "paper_equity_cap": 1000.0,
        "operations": [],
        "logs": [],
        "regime": {},
        "position": {"status": "flat"},
        "active_symbols": [],
    }
    monkeypatch.setattr(
        orbit_exporter.bot_state,
        "load_settings",
        lambda: {"bot_enabled": True},
    )
    payload = orbit_exporter.build_export_payload(live)
    assert payload["trade_count"] == 0
    assert payload["trade_count"] != orbit_exporter.ACCEPTED_METRICS["trade_count"]
    assert payload["research_trade_count"] == 153
    assert payload["equity_usdt"] == 1000.0
    assert payload["status"] == "PAPER"
    assert payload["total_return_pct"] == 0.0
    assert "research_return_pct" in payload
