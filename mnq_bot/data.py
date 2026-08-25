"""Real MNQ/Nasdaq 15-minute history via Yahoo Finance."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from feeds import fetch_first_available

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data_cache"

MNQ_SYMBOLS = ("MNQ=F", "NQ=F", "QQQ")
INTERVAL = "15m"
PERIOD = "60d"


def fetch_mnq_15m(*, force: bool = False, cache_dir: Path | None = CACHE_DIR) -> pd.DataFrame:
    _symbol, frame = fetch_first_available(
        MNQ_SYMBOLS,
        interval=INTERVAL,
        period=PERIOD,
        cache_dir=cache_dir,
        force=force,
    )
    return frame
