"""CLI walk-forward validation for Orbit."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from orbit import config, data, universe
from backtest.config import BacktestConfig
from backtest.walk_forward import ACCEPTANCE, run_walk_forward

CACHE_DIR = Path("data_cache")


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward validation for Orbit.")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--timeframe", default=config.TIMEFRAME)
    parser.add_argument("--output", type=Path, default=Path("backtest_output"))
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()

    cfg = BacktestConfig(
        initial_capital=args.capital,
        universe=tuple(config.UNIVERSE),
        regime_symbol=config.REGIME_SYMBOL,
        **config.get_strategy_params(),
    )
    symbols = universe.symbols_to_fetch(cfg.universe)
    until = datetime.now(timezone.utc)
    print(f"Fetching {len(symbols)} symbols...")
    raw = data.fetch_panel(
        symbols,
        args.timeframe,
        data.history_start_ms(),
        int(until.timestamp() * 1000),
        cache_dir=None if args.no_cache else CACHE_DIR,
        exchange=config.public_exchange,
        on_progress=lambda s, e: print(f"  {s:<12} {'FAIL' if e else 'ok'}"),
    )
    print("Running walk-forward...")
    result = run_walk_forward(raw, cfg, on_progress=lambda f: print(
        f"  {f['test_from']} to {f['test_to']}: {f['test']['total_return_pct']:+.1f}%"
    ))
    agg = result["aggregate"]
    print("\nOOS return %", round(agg["return_pct"], 2), " BTC", round(agg["benchmark_return_pct"], 2))
    print("Sharpe", round(agg["sharpe"], 3), " BTC", round(agg["benchmark_sharpe"], 3))
    for gate, passed in result["gates"].items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {gate}")
    print("VERDICT:", "ACCEPTED" if result["accepted"] else "REJECTED")
    print("Thresholds:", json.dumps(ACCEPTANCE))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "walk_forward.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
