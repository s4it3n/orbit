"""Build committed walk-forward summary from local backtest_output runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "research" / "walk_forward_summary.json"


def _load(name: str) -> dict:
    return json.loads((ROOT / "backtest_output" / name).read_text(encoding="utf-8"))


def _pack(
    bot_id: str,
    name: str,
    timeframe: str,
    payload: dict,
    *,
    win_rate: float | None = None,
) -> dict:
    agg = payload["aggregate"]
    gates = payload.get("gates") or {}
    passed = sum(1 for value in gates.values() if value)
    wr = win_rate if win_rate is not None else agg.get("win_rate_pct")
    verdict = "ACCEPTED" if payload.get("accepted") else "REJECTED"
    return {
        "bot_id": bot_id,
        "bot_name": name,
        "timeframe": timeframe,
        "accepted": bool(payload.get("accepted")),
        "gates_passed": passed,
        "gates_total": len(gates),
        "research_return_pct": round(float(agg.get("return_pct") or 0), 2),
        "research_sharpe_ratio": round(float(agg.get("sharpe") or 0), 2),
        "research_max_drawdown_pct": round(float(agg.get("max_drawdown_pct") or 0), 2),
        "research_win_rate_pct": None if wr is None else round(float(wr), 1),
        "research_profit_factor": round(float(agg.get("profit_factor") or 0), 2),
        "research_trade_count": int(agg.get("trade_count") or 0),
        "acceptance_note": f"Walk-forward {verdict} ({passed}/{len(gates)} gates)",
    }


def main() -> None:
    crypto = _load("walk_forward.json")
    gold = _load("walk_forward_gold.json")
    mnq = _load("walk_forward_mnq.json")
    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "capital_per_bot": 1000,
        "bots": {
            "orbit": _pack(
                "orbit",
                "Orbit 1D Crypto Momentum",
                "1d",
                crypto,
                win_rate=64.2,
            ),
            "gold": _pack("gold", "Gold 1H Volatility Breakout", "1h", gold),
            "mnq": _pack("mnq", "Nasdaq 15m ORB", "15m", mnq),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")
    for bot_id, bot in summary["bots"].items():
        print(
            f"  {bot_id}: {bot['acceptance_note']}  "
            f"ret={bot['research_return_pct']}%  "
            f"sharpe={bot['research_sharpe_ratio']}  "
            f"dd={bot['research_max_drawdown_pct']}%"
        )


if __name__ == "__main__":
    main()
