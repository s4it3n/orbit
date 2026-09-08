# Orbit

Multi-bot paper trading desk. Production UI is FastAPI in `webapp/`.

**Learn the system:** [docs/HOW_ORBIT_WORKS.md](docs/HOW_ORBIT_WORKS.md)

## Layout

| Path | Role |
|---|---|
| `orbit/` | Crypto 1D momentum (Binance spot **testnet**) |
| `gold_bot/` | Gold 1H breakout (Yahoo paper) |
| `mnq_bot/` | QQQ 15m ORB (Yahoo paper; legacy folder name) |
| `paper/` | Shared paper account, fees, flatten, loops |
| `shared/` | Cross-bot utilities (Yahoo feeds) |
| `webapp/` | Password-gated dashboard on `:8080` |
| `backtest/` | Crypto backtest + walk-forward engine |
| `scripts/` | CLI tools (walk-forwards, resets, seeds) |
| `docs/` | Guides |
| `deploy/` | Oracle Cloud / systemd |
| `research/` | Walk-forward summary for the UI |
| `run.py` | Start the platform |

## Secrets

```bash
cp .env.example .env
# Binance testnet keys from https://testnet.binance.vision/ only
```

Never commit `.env`.

## Local run

```bash
python -m venv .venv
# activate venv
pip install -r requirements.txt
cp .env.example .env
python run.py
```

Open http://127.0.0.1:8080 — password `ORBIT_DASHBOARD_PASSWORD` (default `1234`).

With `ORBIT_AUTOSTART=1` (cloud default), crypto + gold + QQQ start enabled.

## Research CLIs (local machine — not the tiny VM)

```bash
python scripts/run_walk_forward.py
python scripts/run_walk_forward_gold.py
python scripts/run_walk_forward_mnq.py
python scripts/build_walk_forward_summary.py
```

## Oracle Cloud

See [deploy/README.md](deploy/README.md). Public site: `http://YOUR_VM_IP:8080`
