"""MNQ bot strategy settings (mnq_settings.json)."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

from . import strategy as mnq_strategy

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = ROOT / "mnq_settings.json"
_lock = threading.RLock()

_DEFAULT_RULES = mnq_strategy.MnqRules()

DEFAULT_SETTINGS: dict[str, Any] = {
    "bot_enabled": False,
    "loop_interval_sec": 90,
    **{f.name: getattr(_DEFAULT_RULES, f.name) for f in fields(_DEFAULT_RULES)},
}


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return deepcopy(default)
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else deepcopy(default)
    except (json.JSONDecodeError, OSError):
        return deepcopy(default)


def _write_json(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    temp.replace(path)


def ensure_settings_file() -> None:
    if not SETTINGS_FILE.exists():
        _write_json(SETTINGS_FILE, DEFAULT_SETTINGS)


def load_settings() -> dict[str, Any]:
    ensure_settings_file()
    stored = _read_json(SETTINGS_FILE, DEFAULT_SETTINGS)
    merged = deepcopy(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in stored.items() if k in merged})
    return merged


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = load_settings()
        allowed = set(DEFAULT_SETTINGS)
        for key, value in updates.items():
            if key in allowed:
                current[key] = value
        _write_json(SETTINGS_FILE, current)
        return current


def rules_from_settings(settings: dict[str, Any] | None = None) -> mnq_strategy.MnqRules:
    s = settings or load_settings()
    base = mnq_strategy.MnqRules()
    kwargs = {f.name: s[f.name] for f in fields(base) if f.name in s}
    return replace(base, **kwargs) if kwargs else base
