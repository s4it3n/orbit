# Orbit

Multi-bot paper trading desk. Production UI is the FastAPI app in `webapp/` (not a separate frontend).

| Module | Path | Role |
|---|---|---|
| Orbit | `orbit/` | ACCEPTED 1D crypto momentum (Binance **spot testnet**) |
| Gold | `gold_bot/` | XAU/USD 1H breakout |
| MNQ | `mnq_bot/` | Micro Nasdaq 15m ORB |
| Dashboard | `webapp/` | Password-gated control panel on `:8080` |
| Backtests | `backtest/` | Shared engine + walk-forward helpers |

## Secrets (important)

API keys live **only** in a local `.env` file (see `.env.example`). That file is gitignored and must never be committed.

```bash
cp .env.example .env
# edit .env with Binance testnet + Telegram values
```

If this repo is public, treat any key that was ever pasted into chat, issues, or commits as compromised and **rotate** it.

## Local run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill keys
python run.py
```

Open http://127.0.0.1:8080 — password from `ORBIT_DASHBOARD_PASSWORD` (default `1234`).

Optional seed for Gold/MNQ dashboard cards:

```bash
python seed_bot_states.py
```

## Walk-forward / backtests (local machine only)

Do **not** run these on the 1 GB Always Free VM.

```bash
python run_walk_forward.py
python run_walk_forward_gold.py
python run_walk_forward_mnq.py
```

## Oracle Cloud (24/7)

See [deploy/README.md](deploy/README.md).

Public site: `http://YOUR_VM_IP:8080`
