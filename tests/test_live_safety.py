"""Live safety: drawdown pause persists."""

from datetime import datetime, timezone

from orbit import engine, state as bot_state


def test_drawdown_guard_stays_paused(tmp_path):
    bot_state.STATE_FILE = tmp_path / "bot_state.json"
    bot_state.SETTINGS_FILE = tmp_path / "settings.json"
    bot_state.ensure_settings_file()
    bot_state.update_state(drawdown_state={
        "day": datetime.now(timezone.utc).date().isoformat(),
        "start_equity": 10_000.0,
        "paused": True,
    })
    engine._guard = None
    guard = engine.get_guard()
    assert guard.trading_paused is True
    assert guard.check(9_500.0) is False
