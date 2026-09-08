"""Rescale crypto paper display when ORBIT_PAPER_EQUITY changes.

Gold/MNQ rescale automatically via ``_ensure_paper_capital``. Crypto uses an
exchange-equity anchor, so we remap ``equity_usdt`` / ``paper_equity_cap`` /
``exchange_equity_anchor`` and scale operation PnL fields.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "bot_state.json"
EXPORT_PATH = ROOT / "orbit_state.json"


def _scale_crypto_state(path: Path, *, new_cap: float, old_cap: float | None) -> dict | None:
    if not path.exists():
        return None
    live = json.loads(path.read_text(encoding="utf-8"))
    stored_cap = float(live.get("paper_equity_cap") or 0.0)
    if stored_cap <= 0:
        stored_cap = float(old_cap) if old_cap is not None else new_cap
    elif old_cap is not None and abs(stored_cap - float(old_cap)) > 1e-9:
        # Already remapped (or drifted) — scale from the ledger's own cap, not a stale CLI flag.
        pass
    elif old_cap is not None:
        stored_cap = float(old_cap)
    if abs(stored_cap - new_cap) < 1e-9:
        return live
    if stored_cap <= 0:
        stored_cap = new_cap
    scale = new_cap / stored_cap if stored_cap else 1.0
    old_equity = live.get("equity_usdt")
    if old_equity is not None:
        # Preserve % P&L vs the previous paper start.
        pnl = float(old_equity) - stored_cap
        live["equity_usdt"] = new_cap + pnl * scale
    live["paper_equity_cap"] = new_cap
    exchange = live.get("exchange_equity_usdt")
    if exchange is not None and live.get("equity_usdt") is not None:
        # Keep display identity: equity = cap + (exchange - anchor)
        live["exchange_equity_anchor"] = float(exchange) - (
            float(live["equity_usdt"]) - new_cap
        )
    for op in list(live.get("operations") or []):
        if op.get("pnl_usdt") is not None:
            op["pnl_usdt"] = float(op["pnl_usdt"]) * scale
    path.write_text(json.dumps(live, indent=2, default=str), encoding="utf-8")
    return live


def main() -> None:
    parser = argparse.ArgumentParser(description="Rescale Orbit crypto paper book.")
    parser.add_argument("--new-cap", type=float, default=100.0)
    parser.add_argument("--old-cap", type=float, default=None)
    args = parser.parse_args()
    live = _scale_crypto_state(STATE_PATH, new_cap=args.new_cap, old_cap=args.old_cap)
    if live is None:
        print(f"No {STATE_PATH}")
    else:
        print(
            f"Scaled {STATE_PATH}: cap={live.get('paper_equity_cap')} "
            f"equity={live.get('equity_usdt')}"
        )
    if EXPORT_PATH.exists():
        EXPORT_PATH.unlink()
        print(f"Removed {EXPORT_PATH} (will regenerate)")


if __name__ == "__main__":
    main()
