"""Yahoo Finance OHLCV fetch with on-disk cache.

Used by Gold and MNQ. Orbit crypto stays on Binance via ``orbit.data``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "data_cache"

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        level0 = [str(col).strip().lower() for col in frame.columns.get_level_values(0)]
        frame = frame.copy()
        frame.columns = level0
    else:
        frame = frame.copy()
        frame.columns = [str(col).strip().lower() for col in frame.columns]
    return frame


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a UTC-timestamped OHLCV frame with a monotonic unique index."""
    if frame is None or frame.empty:
        raise ValueError("Empty OHLCV frame.")
    out = _flatten_columns(frame)
    if "timestamp" not in out.columns:
        idx = out.index
        if not isinstance(idx, pd.DatetimeIndex):
            raise ValueError("OHLCV frame needs a DatetimeIndex or timestamp column.")
        out = out.reset_index()
        ts_col = out.columns[0]
        out = out.rename(columns={ts_col: "timestamp"})
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    rename = {}
    for name in ("open", "high", "low", "close", "volume"):
        matches = [c for c in out.columns if c == name or c.startswith(name)]
        if not matches:
            raise ValueError(f"Missing {name} column in {list(out.columns)}")
        rename[matches[0]] = name
    out = out.rename(columns=rename)
    keep = [c for c in OHLCV_COLUMNS if c in out.columns]
    out = out[keep].copy()
    out["volume"] = out["volume"].fillna(0.0)
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    out = out[out["high"] >= out["low"]]
    out = out.reset_index(drop=True)
    if len(out) < 50:
        raise ValueError(f"Not enough bars after cleanup: {len(out)}")
    return out


def cache_path(symbol: str, interval: str, period: str) -> Path:
    safe = symbol.replace("=", "_").replace("/", "-")
    return CACHE_DIR / f"{safe}_{interval}_{period}.csv"


def fetch_yahoo(
    symbol: str,
    *,
    interval: str,
    period: str,
    cache_dir: Path | None = CACHE_DIR,
    force: bool = False,
) -> pd.DataFrame:
    """Download Yahoo bars, cache as CSV, and return a normalized OHLCV frame."""
    path = None if cache_dir is None else cache_dir / f"{symbol.replace('=', '_').replace('/', '-')}_{interval}_{period}.csv"
    if path is not None and path.exists() and not force:
        cached = pd.read_csv(path)
        return normalize_ohlcv(cached)
    raw = yf.download(
        symbol,
        interval=interval,
        period=period,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError(f"Yahoo returned no data for {symbol} {interval} {period}")
    frame = normalize_ohlcv(raw)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    return frame


def fetch_first_available(
    symbols: tuple[str, ...],
    *,
    interval: str,
    period: str,
    cache_dir: Path | None = CACHE_DIR,
    force: bool = False,
) -> tuple[str, pd.DataFrame]:
    errors: list[str] = []
    for symbol in symbols:
        try:
            return symbol, fetch_yahoo(
                symbol, interval=interval, period=period, cache_dir=cache_dir, force=force
            )
        except Exception as exc:  # noqa: BLE001 — try the next ticker
            errors.append(f"{symbol}: {exc}")
    raise RuntimeError("All Yahoo symbols failed:\n" + "\n".join(errors))
