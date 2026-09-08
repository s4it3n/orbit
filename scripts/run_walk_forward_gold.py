"""CLI walk-forward for Gold 1H."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gold_bot.data import fetch_gold_hourly
from gold_bot.walk_forward import ACCEPTANCE, run_walk_forward


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward validation for Gold 1H.")
    parser.add_argument("--output", type=Path, default=Path("backtest_output"))
    parser.add_argument("--force-fetch", action="store_true")
    args = parser.parse_args()

    print("Fetching GC=F hourly...")
    frame = fetch_gold_hourly(force=args.force_fetch)
    print(f"  bars={len(frame)}  {frame['timestamp'].iloc[0]} -> {frame['timestamp'].iloc[-1]}")
    print("Running walk-forward...")
    result = run_walk_forward(frame, on_progress=lambda f: print(
        f"  {f['test_from']} to {f['test_to']}: {f['test']['total_return_pct']:+.2f}% "
        f"sharpe={f['test']['sharpe_ratio']:+.2f} trades={f['test']['trade_count']}"
    ))
    agg = result["aggregate"]
    print("\nOOS return %", round(agg["return_pct"], 2))
    print("Sharpe", round(agg["sharpe"], 3), "DD", round(agg["max_drawdown_pct"], 2))
    print("Trades", agg["trade_count"], "folds", agg["fold_count"])
    for gate, passed in result["gates"].items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {gate}")
    print("VERDICT:", "ACCEPTED" if result["accepted"] else "REJECTED")
    print("Thresholds:", json.dumps(ACCEPTANCE))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "walk_forward_gold.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    print("Wrote", args.output / "walk_forward_gold.json")


if __name__ == "__main__":
    main()
