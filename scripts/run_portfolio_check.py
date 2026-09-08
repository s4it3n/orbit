"""CLI: local 3-bot portfolio correlation and equity-curve smoothness check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest.portfolio import ACCEPTANCE, run_from_walk_forward_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Equal-weight Orbit + Gold + MNQ portfolio correlation check."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("backtest_output"),
        help="Directory with walk_forward*.json from local WF runners.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backtest_output") / "portfolio_correlation.json",
    )
    args = parser.parse_args()

    print("Loading local walk-forward OOS curves from", args.input)
    result = run_from_walk_forward_dir(args.input)
    agg = result["aggregate"]
    print("\nPairwise correlations:")
    for label, row in result["correlations"].items():
        corr = row.get("correlation")
        days = row.get("overlap_days")
        flag = "ok" if row.get("usable") else "skip"
        corr_s = f"{corr:+.3f}" if corr is not None else "n/a"
        print(f"  [{flag}] {label}: {corr_s}  overlap_days={days}")

    print("\nPortfolio")
    print("  return %", round(agg["return_pct"], 2))
    print("  Sharpe  ", round(agg["sharpe"], 3))
    print("  DD %    ", round(agg["max_drawdown_pct"], 2))
    print("  PF      ", round(agg["profit_factor"], 3))
    print("  max corr", round(agg["max_pairwise_corr"], 3))
    print(
        "  smooth  ",
        "YES" if agg["smooth_smoother"] else "NO",
        f"(port vol {agg['smooth_portfolio_vol']:.5f} vs avg {agg['smooth_avg_bot_vol']:.5f},"
        f" multi-bot days={agg['smooth_multi_bot_days']})",
    )
    print(
        "  DD vs worst bot",
        round(agg["max_drawdown_pct"], 2),
        "vs",
        round(agg["worst_bot_drawdown_pct"], 2),
    )

    for gate, passed in result["gates"].items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {gate}")
    print("VERDICT:", "ACCEPTED" if result["accepted"] else "REJECTED")
    print("Thresholds:", json.dumps(ACCEPTANCE))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Drop bulky curve from console write size? Keep it for dashboards.
    args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
