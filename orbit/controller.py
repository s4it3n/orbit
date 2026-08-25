"""
Bot process controller — start/stop the trading loop from the web dashboard.
"""

from __future__ import annotations

import threading
import traceback
from typing import Callable

from . import state

_stop_event = threading.Event()
_thread: threading.Thread | None = None
_run_once_thread: threading.Thread | None = None
_lock = threading.Lock()
_last_error: str | None = None


def is_running() -> bool:
    with _lock:
        return _thread is not None and _thread.is_alive()


def get_last_error() -> str | None:
    return _last_error


def _run_loop_safe(loop_fn: Callable[[threading.Event], None], stop_event: threading.Event) -> None:
    global _last_error
    try:
        loop_fn(stop_event)
    except Exception as exc:
        _last_error = str(exc)
        state.append_log(f"Bot crashed: {exc}", "ERROR")
        state.append_log(traceback.format_exc(), "ERROR")
        state.append_operation("ERROR", f"Bot crashed: {exc}")
    finally:
        state.set_bot_running(False)


def start(loop_fn: Callable[[threading.Event], None]) -> dict[str, str]:
    global _thread, _last_error

    with _lock:
        if _thread is not None and _thread.is_alive():
            return {"status": "already_running", "ok": True}

        _last_error = None
        _stop_event.clear()
        _thread = threading.Thread(
            target=_run_loop_safe,
            args=(loop_fn, _stop_event),
            daemon=True,
            name="trading-bot",
        )
        _thread.start()

    state.set_bot_running(True)
    state.append_log("Bot started from dashboard", "INFO")
    state.append_operation("START", "Bot started from dashboard")
    return {"status": "started", "ok": True}


def stop() -> dict[str, str]:
    global _thread

    with _lock:
        if _thread is None or not _thread.is_alive():
            state.set_bot_running(False)
            return {"status": "not_running", "ok": True}

        _stop_event.set()
        _thread.join(timeout=15)
        _thread = None

    state.set_bot_running(False)
    state.append_log("Bot stopped from dashboard", "INFO")
    state.append_operation("STOP", "Bot stopped from dashboard")
    return {"status": "stopped", "ok": True}


def run_once(iteration_fn: Callable[[], None]) -> dict[str, str]:
    """Run a single bot iteration in the background (manual trigger)."""
    global _run_once_thread

    with _lock:
        if _run_once_thread is not None and _run_once_thread.is_alive():
            return {"status": "busy", "ok": False, "message": "A run is already in progress"}

        def _task() -> None:
            try:
                state.append_log("Manual run triggered from dashboard", "INFO")
                iteration_fn()
                state.append_log("Manual run completed", "INFO")
            except Exception as exc:
                state.append_log(f"Manual run failed: {exc}", "ERROR")
                state.append_operation("ERROR", f"Manual run failed: {exc}")

        _run_once_thread = threading.Thread(target=_task, daemon=True, name="bot-run-once")
        _run_once_thread.start()

    return {"status": "running", "ok": True, "message": "Running one iteration…"}


def status() -> dict:
    running = is_running()
    state.update_state(bot_running=running)
    return {
        "running": running,
        "last_error": _last_error,
    }
