# Multi-Bot Trading Desk

Four modules live in this repo:

| Module | Path | Role |
|---|---|---|
| Orbit | `orbit/` | ACCEPTED 1D crypto momentum (paper / Binance testnet) |
| Gold | `gold_bot/` | XAU/USD 1H Donchian + ATR squeeze breakout |
| MNQ | `mnq_bot/` | Micro Nasdaq 15m opening-range breakout |
| Dashboard | `web_dashboard/` | Next.js multi-bot control panel |

## Seed bot state JSON

```bash
python seed_bot_states.py
```

Writes `orbit_state.json`, `gold_state.json`, and `mnq_state.json` at the repo root for the dashboard API.

## Orbit paper bot

```bash
python run.py
```

Banner shows **ACCEPTED (9/9 Gates Passed)**. Each cycle also refreshes `orbit_state.json`.

## Gold / MNQ engines

```bash
python -m gold_bot.engine
python -m mnq_bot.engine
```

## Unified dashboard

```bash
cd web_dashboard
npm run dev
```

Open http://localhost:3000 — polls `/api/bots` every 5 seconds.

## Oracle Cloud (24/7)

Click-by-click: [deploy/README.md](deploy/README.md).

Website: `http://YOUR_VM_IP:8080` · password **1234**.


