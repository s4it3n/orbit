"""Market data. Charts and backtests use public Binance (testnet has almost no history)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from . import config

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
DAYS_PER_YEAR = 365.0
HISTORY_START = "2017-08-01"

PANEL_COLUMNS = (
    "open", "high", "low", "close", "trend_ema", "fast_ema", "breadth_ema", "rsi",
    "roc_14", "fast_ema_slope", "fast_streak", "momentum", "volatility", "score",
    "atr", "atr_pct", "dollar_volume", "bars_available",
)

# Bars used to measure the 50-day EMA slope that gates new entries.
EMA_SLOPE_LOOKBACK = 10


def history_start_ms() -> int:
    return int(pd.Timestamp(HISTORY_START, tz="UTC").timestamp() * 1000)


def momentum_columns(lookbacks: Iterable[int]) -> list[str]:
    return [f"roc_{int(p)}" for p in lookbacks]


def round_price(value: float) -> float:
    price = float(value)
    mag = abs(price)
    if mag >= 1000:
        digits = 2
    elif mag >= 1:
        digits = 4
    elif mag >= 0.01:
        digits = 6
    else:
        digits = 8
    return round(price, digits)


def _wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def add_indicators(
    df: pd.DataFrame,
    *,
    trend_ema_period: int | None = None,
    fast_ema_period: int | None = None,
    breadth_ema_period: int | None = None,
    rsi_period: int | None = None,
    momentum_lookbacks: Sequence[int] | None = None,
    volatility_period: int | None = None,
    atr_period: int | None = None,
    volume_lookback: int | None = None,
) -> pd.DataFrame:
    trend_ema_period = trend_ema_period or config.TREND_EMA_PERIOD
    fast_ema_period = fast_ema_period or config.FAST_EMA_PERIOD
    breadth_ema_period = breadth_ema_period or config.BREADTH_EMA_PERIOD
    rsi_period = rsi_period or config.RSI_PERIOD
    momentum_lookbacks = tuple(momentum_lookbacks or config.MOMENTUM_LOOKBACKS)
    volatility_period = volatility_period or config.VOLATILITY_PERIOD
    atr_period = atr_period or config.ATR_PERIOD
    volume_lookback = volume_lookback or config.VOLUME_LOOKBACK
    frame = df.copy()

    frame["trend_ema"] = (
        frame["close"]
        .ewm(span=trend_ema_period, adjust=False, min_periods=trend_ema_period)
        .mean()
    )
    frame["fast_ema"] = (
        frame["close"]
        .ewm(span=fast_ema_period, adjust=False, min_periods=fast_ema_period)
        .mean()
    )
    frame["breadth_ema"] = (
        frame["close"]
        .ewm(span=breadth_ema_period, adjust=False, min_periods=breadth_ema_period)
        .mean()
    )
    frame["rsi"] = _wilder_rsi(frame["close"], rsi_period)
    frame["roc_14"] = frame["close"] / frame["close"].shift(14) - 1.0
    frame["above_trend"] = frame["close"] > frame["trend_ema"]

    frame["fast_ema_slope"] = (
        frame["fast_ema"] / frame["fast_ema"].shift(EMA_SLOPE_LOOKBACK) - 1.0
    )
    above_fast = frame["close"] > frame["fast_ema"]
    frame["fast_streak"] = (
        above_fast.groupby((~above_fast).cumsum()).cumsum().astype(float)
    )

    cols = momentum_columns(momentum_lookbacks)
    for period, column in zip(momentum_lookbacks, cols):
        frame[column] = frame["close"] / frame["close"].shift(int(period)) - 1.0
    frame["momentum"] = frame[cols].mean(axis=1, skipna=False)

    returns = frame["close"].pct_change()
    frame["volatility"] = returns.rolling(
        volatility_period, min_periods=volatility_period
    ).std(ddof=0) * np.sqrt(DAYS_PER_YEAR)
    frame["score"] = frame["momentum"] / frame["volatility"].replace(0.0, np.nan)

    prev = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev).abs(),
            (frame["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = tr.ewm(
        alpha=1 / atr_period, adjust=False, min_periods=atr_period
    ).mean()
    frame["atr_pct"] = frame["atr"] / frame["close"].replace(0.0, np.nan)
    frame["dollar_volume"] = (
        (frame["close"] * frame["volume"])
        .rolling(volume_lookback, min_periods=volume_lookback)
        .median()
    )
    frame["bars_available"] = np.arange(1, len(frame) + 1, dtype=float)
    return frame


# Back-compat alias used by older call sites during migration.
_add_indicators = add_indicators


def warmup_bars(
    *,
    trend_ema_period: int | None = None,
    fast_ema_period: int | None = None,
    breadth_ema_period: int | None = None,
    rsi_period: int | None = None,
    momentum_lookbacks: Sequence[int] | None = None,
    volatility_period: int | None = None,
    atr_period: int | None = None,
    volume_lookback: int | None = None,
) -> int:
    trend_ema_period = trend_ema_period or config.TREND_EMA_PERIOD
    fast_ema_period = fast_ema_period or config.FAST_EMA_PERIOD
    breadth_ema_period = breadth_ema_period or config.BREADTH_EMA_PERIOD
    rsi_period = rsi_period or config.RSI_PERIOD
    momentum_lookbacks = tuple(momentum_lookbacks or config.MOMENTUM_LOOKBACKS)
    volatility_period = volatility_period or config.VOLATILITY_PERIOD
    atr_period = atr_period or config.ATR_PERIOD
    volume_lookback = volume_lookback or config.VOLUME_LOOKBACK
    return int(
        max(
            trend_ema_period,
            fast_ema_period,
            breadth_ema_period,
            rsi_period,
            max(momentum_lookbacks),
            volatility_period,
            atr_period,
            volume_lookback,
        )
        + 2
    )


def fetch_ohlcv(
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int | None = None,
    *,
    public: bool = True,
) -> pd.DataFrame:
    """Fetch candles. Default uses public Binance so charts have real history."""
    symbol = symbol or config.REGIME_SYMBOL
    timeframe = timeframe or config.TIMEFRAME
    limit = limit or config.CANDLE_LIMIT
    client = config.public_exchange if public else config.exchange
    rows = client.fetch_ohlcv(symbol, timeframe, limit=limit)
    frame = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return add_indicators(frame)


def cache_path(
    cache_dir: Path | None,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
) -> Path | None:
    if cache_dir is None:
        return None
    since = pd.Timestamp(since_ms, unit="ms", tz="UTC").date()
    until = pd.Timestamp(until_ms, unit="ms", tz="UTC").date()
    slug = symbol.replace("/", "-")
    return Path(cache_dir) / f"public_{slug}_{timeframe}_{since}_{until}.csv"


def fetch_raw_history(
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    *,
    cache_file: Path | None = None,
    exchange: Any | None = None,
) -> pd.DataFrame:
    if cache_file and cache_file.exists():
        frame = pd.read_csv(cache_file, parse_dates=["timestamp"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame

    exchange = exchange or config.public_exchange
    timeframe_ms = int(exchange.parse_timeframe(timeframe) * 1000)
    cursor = since_ms
    rows: list[list[float]] = []
    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(row for row in batch if int(row[0]) < until_ms)
        next_cursor = int(batch[-1][0]) + timeframe_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 1000:
            break
    if not rows:
        raise ValueError(f"No historical candles returned for {symbol}.")
    frame = pd.DataFrame(rows, columns=OHLCV_COLUMNS).drop_duplicates(subset=["timestamp"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    if cache_file:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(cache_file, index=False)
    return frame


def fetch_historical_ohlcv(
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    *,
    cache_file: Path | None = None,
    exchange: Any | None = None,
    **indicator_kwargs: Any,
) -> pd.DataFrame:
    frame = fetch_raw_history(
        symbol, timeframe, since_ms, until_ms,
        cache_file=cache_file, exchange=exchange,
    )
    return add_indicators(frame, **indicator_kwargs)


def fetch_panel(
    symbols: Sequence[str],
    timeframe: str,
    since_ms: int,
    until_ms: int,
    *,
    cache_dir: Path | None = None,
    exchange: Any | None = None,
    skip_errors: bool = True,
    on_progress: Any | None = None,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frames[symbol] = fetch_raw_history(
                symbol, timeframe, since_ms, until_ms,
                cache_file=cache_path(cache_dir, symbol, timeframe, since_ms, until_ms),
                exchange=exchange or config.public_exchange,
            )
        except Exception as exc:
            if not skip_errors:
                raise
            if on_progress:
                on_progress(symbol, exc)
            continue
        if on_progress:
            on_progress(symbol, None)
    if not frames:
        raise ValueError("No symbols returned usable history.")
    return frames


def apply_indicators(frames: dict[str, pd.DataFrame], **kwargs: Any) -> dict[str, pd.DataFrame]:
    return {symbol: add_indicators(frame, **kwargs) for symbol, frame in frames.items()}


@dataclass(frozen=True)
class Panel:
    dates: pd.DatetimeIndex
    symbols: tuple[str, ...]
    data: dict[str, np.ndarray]

    def __len__(self) -> int:
        return len(self.dates)

    def row(self, column: str, index: int) -> np.ndarray:
        return self.data[column][index]

    def value(self, column: str, index: int, symbol_index: int) -> float:
        return float(self.data[column][index][symbol_index])

    def index_of(self, symbol: str) -> int:
        return self.symbols.index(symbol)

    def slice_dates(self, start: pd.Timestamp, end: pd.Timestamp) -> "Panel":
        mask = (self.dates >= start) & (self.dates < end)
        positions = np.flatnonzero(mask)
        if positions.size == 0:
            raise ValueError("Date slice contains no bars.")
        return Panel(
            dates=self.dates[positions],
            symbols=self.symbols,
            data={name: values[positions] for name, values in self.data.items()},
        )


def align_panel(
    frames: dict[str, pd.DataFrame],
    columns: Sequence[str] = PANEL_COLUMNS,
) -> Panel:
    if not frames:
        raise ValueError("Cannot align an empty panel.")
    symbols = tuple(frames.keys())
    index: pd.DatetimeIndex | None = None
    for frame in frames.values():
        stamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
        index = stamps if index is None else index.union(stamps)
    assert index is not None
    index = index.sort_values()
    data = {name: np.full((len(index), len(symbols)), np.nan, dtype=float) for name in columns}
    for position, symbol in enumerate(symbols):
        frame = frames[symbol]
        stamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
        aligned = frame.set_index(stamps).reindex(index)
        for name in columns:
            if name in aligned.columns:
                data[name][:, position] = pd.to_numeric(
                    aligned[name], errors="coerce"
                ).to_numpy(dtype=float)
    return Panel(dates=index, symbols=symbols, data=data)


def candles_for_chart(df: pd.DataFrame) -> list[dict]:
    rows = []
    for _, row in df.iterrows():
        ts = row["timestamp"]
        trend = row.get("trend_ema")
        rows.append({
            "time": int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts) // 1000,
            "open": round_price(row["open"]),
            "high": round_price(row["high"]),
            "low": round_price(row["low"]),
            "close": round_price(row["close"]),
            "trend_ema": round_price(trend) if pd.notna(trend) else None,
        })
    return rows


def get_completed_candles(df: pd.DataFrame, count: int = 2) -> pd.DataFrame:
    if len(df) < count + 1:
        raise ValueError(
            f"Need at least {count + 1} candles to extract {count} completed bars."
        )
    return df.iloc[-(count + 1):-1].reset_index(drop=True)
