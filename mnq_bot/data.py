"""Real QQQ 15-minute history via Yahoo Finance (Nasdaq-100 ETF day desk)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from shared.feeds import fetch_first_available

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data_cache"

# Prefer the ETF directly — matches fractional-share paper sizing.
QQQ_SYMBOLS = ("QQQ",)
INTERVAL = "15m"
PERIOD = "60d"

# Legacy name kept for callers.
MNQ_SYMBOLS = QQQ_SYMBOLS


def fetch_mnq_15m(*, force: bool = False, cache_dir: Path | None = CACHE_DIR) -> pd.DataFrame:
    _symbol, frame = fetch_first_available(
        QQQ_SYMBOLS,
        interval=INTERVAL,
        period=PERIOD,
        cache_dir=cache_dir,
        force=force,
    )
    return frame
