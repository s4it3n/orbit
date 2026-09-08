"""Seed dashboard JSON snapshots for Orbit, Gold, and MNQ."""

from __future__ import annotations

from gold_bot.data import fetch_gold_hourly
from gold_bot.engine import export_state as export_gold
from gold_bot.engine import run_backtest as run_gold
from mnq_bot.data import fetch_mnq_15m
from mnq_bot.engine import export_state as export_mnq
from mnq_bot.engine import run_backtest as run_mnq
from orbit import exporter as orbit_exporter


def main() -> None:
    orbit = orbit_exporter.export_state()
    gold_result = run_gold(fetch_gold_hourly())
    gold = export_gold(gold_result, status="PAPER")
    mnq_result = run_mnq(fetch_mnq_15m())
    mnq = export_mnq(mnq_result, status="PAPER")
    print("orbit_state.json", orbit["total_return_pct"], orbit["status"])
    print(
        "gold_state.json",
        gold["total_return_pct"],
        gold["sharpe_ratio"],
        gold["trade_count"],
        gold.get("data_source"),
    )
    print(
        "mnq_state.json",
        mnq["total_return_pct"],
        mnq["sharpe_ratio"],
        mnq["trade_count"],
        mnq.get("data_source"),
    )


if __name__ == "__main__":
    main()
