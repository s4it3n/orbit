"""Fresh-start paper books for Orbit crypto, Gold, and MNQ.

Flattens any open crypto testnet lots, wipes trade/ops history, and resets
each desk to its paper capital:

  Crypto  ORBIT_PAPER_EQUITY   (default 100)
  Gold    GOLD_PAPER_EQUITY    (default 100)
  MNQ     MNQ_PAPER_EQUITY     (default 500 — margin floor for 1 lot)

Usage (from repo root, service stopped preferred):

  python scripts/reset_paper_books.py
  python scripts/reset_paper_books.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _cap(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    return float(raw)


def _flatten_crypto(*, dry_run: bool) -> dict:
    """Market-sell open Orbit lots on the exchange, then wipe bot state."""
    from orbit import config
    from orbit import execution
    from orbit import state as bot_state

    paper_cap = _cap("ORBIT_PAPER_EQUITY", 100.0)
    live = bot_state.load_state()
    book = list(live.get("positions") or [])
    pos = live.get("position") or {}
    if not book and pos.get("status") == "long" and pos.get("symbol"):
        book = [pos]

    sold: list[str] = []
    if not dry_run and book:
        config.exchange.load_markets()
        for item in book:
            symbol = str(item.get("symbol") or "")
            if not symbol:
                continue
            try:
                execution.cancel_open_orders(config.exchange, symbol)
                snap = execution.fetch_balances(config.exchange, symbol)
                ticker = config.exchange.fetch_ticker(symbol)
                price = float(ticker.get("last") or item.get("entry_price") or 0.0)
                qty = execution.normalize_quantity(
                    config.exchange,
                    symbol,
                    min(float(item.get("quantity") or 0.0), snap.base_free),
                    price,
                )
                if qty <= 0:
                    sold.append(f"{symbol}: nothing to sell")
                    continue
                fill = execution.place_market_order(
                    config.exchange,
                    symbol,
                    "sell",
                    qty,
                    price,
                    execution.client_order_id(symbol, _utc_now(), "reset"),
                )
                sold.append(f"{symbol}: sold {fill.quantity} @ {fill.average_price}")
            except Exception as exc:  # noqa: BLE001 — reset must continue
                sold.append(f"{symbol}: flatten failed ({exc})")

    exchange_equity = None
    if not dry_run:
        try:
            snap = execution.fetch_balances(config.exchange, config.REGIME_SYMBOL)
            exchange_equity = float(snap.quote_total)
            # Include leftover dust bases if priced.
            for item in book:
                symbol = str(item.get("symbol") or "")
                if not symbol:
                    continue
                try:
                    held = execution.fetch_balances(config.exchange, symbol)
                    ticker = config.exchange.fetch_ticker(symbol)
                    px = float(ticker.get("last") or 0.0)
                    exchange_equity += float(held.base_total) * px
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001
            sold.append(f"balance refresh failed ({exc})")

    fresh = deepcopy(bot_state.DEFAULT_STATE)
    fresh.update({
        "bot_running": False,
        "equity_usdt": paper_cap,
        "cash_usdt": paper_cap,
        "paper_cash_usdt": paper_cap,
        "open_pnl_usdt": 0.0,
        "balance_usdt": None,
        "paper_equity_cap": paper_cap,
        "paper_cost_drag": 0.0,
        "exchange_equity_usdt": exchange_equity,
        "exchange_equity_anchor": exchange_equity,
        "start_of_day_balance": paper_cap,
        "daily_drawdown_pct": 0.0,
        "trading_paused": False,
        "pause_reason": None,
        "drawdown_state": {"day": None, "start_equity": 0.0, "paused": False},
        "last_processed_candle_ts": None,
        "cooldown_days_remaining": 0,
        "operations": [{
            "time": _utc_now(),
            "type": "RESET",
            "detail": f"Fresh paper start @ {paper_cap:.2f} USDT",
        }],
        "logs": [{
            "time": _utc_now(),
            "level": "INFO",
            "message": f"Paper books reset — crypto {paper_cap:.0f} USDT",
        }],
        "last_updated": _utc_now(),
    })
    if not dry_run:
        _write(bot_state.STATE_FILE, fresh)
        export = ROOT / "orbit_state.json"
        if export.exists():
            export.unlink()
    return {
        "paper_cap": paper_cap,
        "sold": sold,
        "exchange_equity": exchange_equity,
        "path": str(bot_state.STATE_FILE),
    }


def _reset_yahoo_bot(bot: str, paper_cap: float, *, dry_run: bool) -> dict:
    if bot == "gold":
        from gold_bot import live as mod
        account_path = mod.ACCOUNT_PATH
        state_path = mod.STATE_PATH
        symbol = "XAUUSD"
    else:
        from mnq_bot import live as mod
        account_path = mod.ACCOUNT_PATH
        state_path = mod.STATE_PATH
        symbol = "MNQ"

    account = {
        "bot_id": bot,
        "initial_capital": paper_cap,
        "cash": paper_cap,
        "position": None,
        "trades": [],
        "equity_curve": [{"timestamp": _utc_now(), "equity": paper_cap}],
        "logs": [{
            "time": _utc_now(),
            "level": "INFO",
            "message": f"Paper books reset — {bot} {paper_cap:.0f} USDT",
        }],
        "last_processed_bar_ts": None,
    }
    if bot == "mnq":
        account.update({
            "or_high": None,
            "or_low": None,
            "trades_today": 0,
            "current_day": None,
        })

    state = {
        "bot_id": bot,
        "bot_name": "QQQ 15m ORB" if bot == "mnq" else ("Gold Breakout" if bot == "gold" else bot),
        "asset_class": "QQQ ETF" if bot == "mnq" else ("Gold / XAU" if bot == "gold" else bot),
        "timeframe": "1h" if bot == "gold" else "15m",
        "status": "IDLE",
        "mode": "paper_live",
        "updated_at": _utc_now(),
        "cash_usdt": paper_cap,
        "equity_usdt": paper_cap,
        "open_pnl_usdt": 0.0,
        "total_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "win_rate_pct": 0.0,
        "profit_factor": 0.0,
        "trade_count": 0,
        "current_position": None,
        "equity_curve": [{"timestamp": _utc_now(), "equity": paper_cap}],
        "recent_trades": [],
        "logs": account["logs"],
        "symbol": "QQQ" if bot == "mnq" else symbol,
    }
    if not dry_run:
        _write(account_path, account)
        _write(state_path, state)
    return {
        "paper_cap": paper_cap,
        "account": str(account_path),
        "state": str(state_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset Orbit paper books to a fresh start.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-flatten", action="store_true", help="Do not place crypto sell orders")
    args = parser.parse_args()

    # Load .env so paper caps / exchange keys resolve.
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass

    crypto_cap = _cap("ORBIT_PAPER_EQUITY", 100.0)
    gold_cap = _cap("GOLD_PAPER_EQUITY", crypto_cap)
    mnq_cap = _cap("MNQ_PAPER_EQUITY", 100.0)

    print(f"Caps → crypto {crypto_cap:.0f} | gold {gold_cap:.0f} | mnq {mnq_cap:.0f}")
    if args.dry_run:
        print("DRY RUN — no files or orders will change")

    if args.skip_flatten:
        # Still wipe crypto state without selling.
        os.environ.setdefault("ORBIT_PAPER_EQUITY", str(crypto_cap))
        from orbit import state as bot_state
        fresh = deepcopy(bot_state.DEFAULT_STATE)
        fresh.update({
            "equity_usdt": crypto_cap,
            "cash_usdt": crypto_cap,
            "paper_cash_usdt": crypto_cap,
            "open_pnl_usdt": 0.0,
            "paper_equity_cap": crypto_cap,
            "paper_cost_drag": 0.0,
            "operations": [],
            "logs": [],
            "drawdown_state": {"day": None, "start_equity": 0.0, "paused": False},
            "last_updated": _utc_now(),
        })
        if not args.dry_run:
            _write(bot_state.STATE_FILE, fresh)
            export = ROOT / "orbit_state.json"
            if export.exists():
                export.unlink()
        crypto = {"paper_cap": crypto_cap, "sold": ["skipped flatten"], "path": str(bot_state.STATE_FILE)}
    else:
        crypto = _flatten_crypto(dry_run=args.dry_run)

    gold = _reset_yahoo_bot("gold", gold_cap, dry_run=args.dry_run)
    mnq = _reset_yahoo_bot("mnq", mnq_cap, dry_run=args.dry_run)

    print("crypto:", crypto)
    print("gold:", gold)
    print("mnq:", mnq)
    print("Done." if not args.dry_run else "Dry run complete.")


if __name__ == "__main__":
    main()
