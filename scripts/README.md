# CLI helpers (run from the repo root so imports resolve)

| Script | Purpose |
|---|---|
| `run.py` (repo root) | Start the web dashboard + optional autostart |
| `scripts/run_backtest.py` | One-shot crypto backtest |
| `scripts/run_walk_forward.py` | Crypto walk-forward research |
| `scripts/run_walk_forward_gold.py` | Gold walk-forward |
| `scripts/run_walk_forward_mnq.py` | QQQ/ORB walk-forward (legacy `mnq` name) |
| `scripts/run_portfolio_check.py` | Multi-bot portfolio sanity check |
| `scripts/seed_bot_states.py` | Refresh dashboard JSON snapshots from research |
| `scripts/reset_paper_books.py` | Flatten crypto + reset ~$100 paper books |
| `scripts/build_walk_forward_summary.py` | Rebuild `research/walk_forward_summary.json` |
| `scripts/rescale_crypto_paper.py` | Rescale crypto display after capital change |

Root shims (`run_walk_forward.py`, etc.) still work; they forward into this folder.
