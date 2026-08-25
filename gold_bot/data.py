"""Real XAU/USD hourly history via Yahoo Finance (GC=F)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from feeds import fetch_first_available

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data_cache"

GOLD_SYMBOLS = ("GC=F",)
INTERVAL = "1h"
PERIOD = "730d"


def fetch_gold_hourly(*, force: bool = False, cache_dir: Path | None = CACHE_DIR) -> pd.DataFrame:
    _symbol, frame = fetch_first_available(
        GOLD_SYMBOLS,
        interval=INTERVAL,
        period=PERIOD,
        cache_dir=cache_dir,
        force=force,
    )
    return frame
