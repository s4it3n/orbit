"""Named background loops for Orbit / Gold / MNQ paper bots."""

from __future__ import annotations

import threading
import traceback
from typing import Callable

_lock = threading.Lock()
_loops: dict[str, dict[str, object]] = {}


def is_running(name: str) -> bool:
    with _lock:
        meta = _loops.get(name)
        if not meta:
            return False
        thread = meta.get("thread")
        return isinstance(thread, threading.Thread) and thread.is_alive()


def start(name: str, loop_fn: Callable[[threading.Event], None]) -> dict[str, object]:
    with _lock:
        meta = _loops.get(name)
        if meta:
            thread = meta.get("thread")
            if isinstance(thread, threading.Thread) and thread.is_alive():
                return {"ok": True, "status": "already_running", "bot": name}

        stop_event = threading.Event()

        def _safe() -> None:
            try:
                loop_fn(stop_event)
            except Exception:
                traceback.print_exc()
            finally:
                with _lock:
                    current = _loops.get(name)
                    if current and current.get("thread") is threading.current_thread():
                        _loops.pop(name, None)

        thread = threading.Thread(
            target=_safe,
            daemon=True,
            name=f"{name}-paper-bot",
        )
        _loops[name] = {"thread": thread, "stop": stop_event}
        thread.start()
    return {"ok": True, "status": "started", "bot": name}


def stop(name: str, timeout: float = 20.0) -> dict[str, object]:
    with _lock:
        meta = _loops.get(name)
        if not meta:
            return {"ok": True, "status": "not_running", "bot": name}
        stop_event = meta.get("stop")
        thread = meta.get("thread")
        if isinstance(stop_event, threading.Event):
            stop_event.set()
    if isinstance(thread, threading.Thread):
        thread.join(timeout=timeout)
    with _lock:
        meta = _loops.get(name)
        if meta and meta.get("thread") is thread:
            _loops.pop(name, None)
    return {"ok": True, "status": "stopped", "bot": name}


def stop_all(timeout: float = 20.0) -> None:
    with _lock:
        names = list(_loops.keys())
    for name in names:
        stop(name, timeout=timeout)


def status(name: str) -> dict[str, object]:
    return {"bot": name, "running": is_running(name)}
