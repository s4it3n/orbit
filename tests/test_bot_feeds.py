"""Gold / MNQ walk-forward gates and Yahoo feed helpers."""

import pandas as pd

from feeds import normalize_ohlcv
from gold_bot.walk_forward import ACCEPTANCE as GOLD_ACCEPTANCE
from mnq_bot.walk_forward import ACCEPTANCE as MNQ_ACCEPTANCE


def test_gold_gates_pre_registered():
    assert GOLD_ACCEPTANCE["min_sharpe"] == 0.60
    assert GOLD_ACCEPTANCE["min_return_pct"] == 0.0
    assert GOLD_ACCEPTANCE["max_drawdown_limit_pct"] == -7.0


def test_mnq_gates_pre_registered():
    assert MNQ_ACCEPTANCE["min_sharpe"] == 0.50
    assert MNQ_ACCEPTANCE["min_return_pct"] == 0.0
    assert MNQ_ACCEPTANCE["min_trades"] == 6
    assert MNQ_ACCEPTANCE["min_profit_factor"] == 1.20


def test_normalize_ohlcv():
    idx = pd.date_range("2024-01-01", periods=60, freq="1h", tz="UTC")
    frame = pd.DataFrame({
        "Open": 10.0,
        "High": 11.0,
        "Low": 9.0,
        "Close": 10.5,
        "Volume": 100,
    }, index=idx)
    out = normalize_ohlcv(frame)
    assert list(out.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert out["timestamp"].dt.tz is not None
    assert len(out) == 60
