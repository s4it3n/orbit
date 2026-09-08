"""CLI backtest for Orbit."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from orbit import config, data, universe
from backtest.config import BacktestConfig
from backtest.engine import run_backtest
from backtest.metrics import calculate_metrics
from backtest.report import print_report, write_report

CACHE_DIR = Path("data_cache")


def _date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def build_panel(cfg: BacktestConfig, timeframe: str, until: datetime, *, use_cache: bool = True, verbose: bool = True) -> data.Panel:
    symbols = universe.symbols_to_fetch(cfg.universe)

    def progress(symbol: str, error: Exception | None) -> None:
        if verbose:
            print(f"  {symbol:<12} {'FAILED: ' + str(error)[:60] if error else 'ok'}")

    if verbose:
        print(f"Fetching {len(symbols)} symbols of {timeframe} history...")
    raw = data.fetch_panel(
        symbols,
        timeframe,
        data.history_start_ms(),
        int(until.timestamp() * 1000),
        cache_dir=CACHE_DIR if use_cache else None,
        exchange=config.public_exchange,
        on_progress=progress,
    )
    return data.align_panel(data.apply_indicators(raw, **cfg.indicator_params()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Orbit.")
    parser.add_argument("--timeframe", default=config.TIMEFRAME)
    parser.add_argument("--since", type=_date)
    parser.add_argument("--until", type=_date)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--output", type=Path, default=Path("backtest_output"))
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    until = args.until or datetime.now(timezone.utc)
    since = args.since or until - timedelta(days=args.days)
    cfg = BacktestConfig(
        initial_capital=args.capital,
        universe=tuple(config.UNIVERSE),
        regime_symbol=config.REGIME_SYMBOL,
        **config.get_strategy_params(),
    )
    panel = build_panel(cfg, args.timeframe, until, use_cache=not args.no_cache)
    window = panel.slice_dates(
        pd.Timestamp(since).tz_convert("UTC"),
        pd.Timestamp(until).tz_convert("UTC"),
    )
    print(f"Testing {window.dates[0].date()} to {window.dates[-1].date()} ({len(window)} bars)")
    result = run_backtest(window, cfg)
    metrics = calculate_metrics(result, window, cfg)
    print_report(metrics)
    write_report(metrics, result, args.output)


if __name__ == "__main__":
    main()
