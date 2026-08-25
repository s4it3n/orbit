"""Walk-forward gate definitions."""

from backtest.walk_forward import ACCEPTANCE


def test_gates_pre_registered():
    assert ACCEPTANCE["min_profit_factor"] == 1.20
    assert ACCEPTANCE["min_positive_fold_pct"] == 60.0
    assert ACCEPTANCE["max_drawdown_limit_pct"] == -25.0
