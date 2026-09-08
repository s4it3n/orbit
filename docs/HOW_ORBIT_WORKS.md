# How Orbit Works — Complete Learning Guide

This is the single document that explains **Orbit** from zero to “I understand every major moving part.”  
You do not need prior trading knowledge. Read top to bottom once; later use the table of contents as a map.

---

## Table of contents

1. [What Orbit is](#1-what-orbit-is)
2. [Trading basics you need](#2-trading-basics-you-need)
3. [The three-bot desk](#3-the-three-bot-desk)
4. [Repository map (clean layout)](#4-repository-map-clean-layout)
5. [How a process boots and runs](#5-how-a-process-boots-and-runs)
6. [Bot 1 — Crypto (daily momentum)](#6-bot-1--crypto-daily-momentum)
7. [Bot 2 — Gold (hourly breakout)](#7-bot-2--gold-hourly-breakout)
8. [Bot 3 — QQQ (15m opening range)](#8-bot-3--qqq-15m-opening-range)
9. [Paper money, cash vs equity, fees](#9-paper-money-cash-vs-equity-fees)
10. [Website, Start/Stop, Flatten](#10-website-startstop-flatten)
11. [Telegram](#11-telegram)
12. [Walk-forward research](#12-walk-forward-research)
13. [Running locally and on the VM](#13-running-locally-and-on-the-vm)
14. [Failure modes and safety](#14-failure-modes-and-safety)
15. [Honest limitations](#15-honest-limitations)
16. [Glossary](#16-glossary)
17. [Code index](#17-code-index)

---

## 1. What Orbit is

Orbit is a **paper trading desk**: three automated strategies that trade with about **$100 each** (~**$300** combined) so you can watch real rules against real-ish market data **without risking live capital**.

| Desk | Trades | Cadence | Data | Where “orders” go |
|---|---|---|---|---|
| **Crypto** (`orbit/`) | Big-cap crypto vs USDT | Decisions on **completed daily** bars; loop ~60s | Binance public history | Binance **spot testnet** |
| **Gold** (`gold_bot/`) | Gold futures proxy `GC=F` | **1h** bars; loop ~3 min | Yahoo Finance | Local JSON paper ledger |
| **QQQ** (`mnq_bot/` folder) | Nasdaq-100 ETF shares | **15m** bars in US session | Yahoo Finance | Local JSON paper ledger |

A password-protected site on port **8080** shows cash, equity, open trades, logs, and research badges. Optional Telegram messages fire on fills and once per day.

**Research ACCEPTED ≠ future profit.** Walk-forwards say “these rules looked good on past out-of-sample windows,” not “you will make money.”

---

## 2. Trading basics you need

### Price, long, short

- **Price** — what buyers/sellers agree for one unit (1 SOL, 1 paper gold ounce, 1 QQQ share).
- **Long** — buy first, hope it rises, sell later.
- **Short** — sell first (or bet down), hope it falls, buy back. Gold and QQQ can short; crypto Orbit is **long-only**.

### Candles (bars)

Each candle has open / high / low / close for a time bucket:

- Crypto → **1 day**
- Gold → **1 hour**
- QQQ → **15 minutes**

Strategies usually act on **completed** candles (not the still-forming one).

### Indicators (intuition only)

| Name | Meaning |
|---|---|
| **EMA** | Smoothed recent average price (“trend”). |
| **RSI** | 0–100 “has it run too hard?” meter. |
| **ATR** | Typical wiggle size — used to place stops. |
| **Momentum / ROC** | How much price rose over N bars. |
| **Volatility** | How jumpy returns are — riskier names get smaller size. |

Mental model: **regime filter → rank ideas → size risk → hard exits.**

### Stops

- **Stop-loss** — exit if price moves against you.
- **Take-profit** — exit (sometimes partial) when far enough in your favor.
- **Trailing stop** — stop that ratchets up as price makes new highs.

### Paper vs live; backtest vs walk-forward

- **Paper** — fake money, real rules/prices (Orbit).
- **Live** — real money at a broker (not this repo’s job).
- **Backtest** — run rules once on history (easy to overfit).
- **Walk-forward** — train on window A, test on next untouched B, roll forward; gates decide ACCEPTED.

---

## 3. The three-bot desk

```
┌──────────────────────────────────────────────┐
│                  Orbit desk                   │
│   Crypto ~$100    Gold ~$100    QQQ ~$100     │
│         combined equity ≈ sum of three        │
└──────────────────────────────────────────────┘
```

- Separate piggy banks — a gold loss does **not** auto-sell crypto.
- Env knobs: `ORBIT_PAPER_EQUITY`, `GOLD_PAPER_EQUITY`, `MNQ_PAPER_EQUITY` (QQQ uses the MNQ env name for history).
- Platform “Cash (idle)” / “Equity (total)” combine the three desks.

### Why three markets?

Diversification: crypto, gold, and US mega-cap tech often move for different reasons.

### Speed expectations

| Desk | How “fast” it feels |
|---|---|
| Crypto | Slow — at most one slot; new rotates mainly on **new daily** bars |
| Gold | Medium — can trade several times a week when squeezes break |
| QQQ | Session-bound — only during US open window on weekdays |

Weekends and holidays: gold/QQQ often show **0 new bars**; that is normal.

---

## 4. Repository map (clean layout)

```
orbit/                 Crypto bot (strategy, engine, Binance execution, Telegram, export)
gold_bot/              Gold 1H breakout + live paper loop
mnq_bot/               QQQ 15m ORB (legacy folder name “mnq”)
paper/                 Shared paper helpers, costs, flatten, background loops
shared/                Cross-bot utilities (Yahoo OHLCV feeds)
webapp/                FastAPI site + HTML templates (the real UI)
backtest/              Crypto backtest engine + walk-forward
scripts/               CLI tools (walk-forwards, reset books, seed states)
docs/                  This guide + archived notes
deploy/                Oracle Cloud install / systemd
research/              Committed walk-forward summary for the UI
tests/                 Automated tests
run.py                 Start the platform (only root process entry you need daily)
feeds.py               Tiny shim → shared.feeds (back-compat)
```

**Not used in production:** `web_dashboard/` (old Next.js prototype; gitignored).

### Runtime files (repo root / `/opt/orbit` on the VM)

These are **live state**, usually gitignored:

| File | Role |
|---|---|
| `.env` | Secrets + capital/fee knobs |
| `settings.json` | Crypto strategy knobs (UI-editable) |
| `gold_settings.json` / `mnq_settings.json` | Gold / QQQ knobs + `bot_enabled` |
| `bot_state.json` | Crypto engine truth (positions, ops, cash ledger) |
| `orbit_state.json` | Crypto card snapshot for the platform |
| `gold_live.json` / `mnq_live.json` | Paper account ledgers |
| `gold_state.json` / `mnq_state.json` | UI snapshots |
| `desk_daily.json` | Telegram daily open-of-day anchors |

### Scripts folder

See `scripts/README.md`. Examples:

```bash
python run.py
python scripts/reset_paper_books.py
python scripts/run_walk_forward.py
```

Root names like `run_walk_forward.py` still work as thin forwarders.

---

## 5. How a process boots and runs

1. **`python run.py`** starts Uvicorn → `webapp.server:app`.
2. If **`ORBIT_AUTOSTART=1`** (VM default):
   - Crypto: `settings.json` → `bot_enabled=true`, start `orbit.engine` loop.
   - Gold/QQQ: `set_enabled(True)` (writes `*_settings.json`) + start `paper.loops` threads.
3. Each loop wakes every N seconds → fetch data → maybe trade → write JSON → sleep.
4. The website **reads JSON**; it does not place orders itself (except Start/Stop/Flatten APIs).

### Critical: `bot_enabled` vs “thread running”

A background thread can be alive while **`bot_enabled: false`**. Then the bot logs “started” but **skips trading**.  

Autostart must set **both** the loop and `bot_enabled`. Start/Stop on the UI does that correctly. Flatten **pauses** (`bot_enabled=false`) on purpose so positions do not reopen.

---

## 6. Bot 1 — Crypto (daily momentum)

**UI name:** Orbit 1D Crypto Momentum  
**Code:** `orbit/strategy.py`, `orbit/engine.py`, `orbit/execution.py`

**One sentence:** Only risk when BTC looks healthy; hold the best momentum/volatility coin; size carefully; exit with ATR stops/trails/TP; flatten on danger.

### Universe

BTC, ETH, BNB, SOL, XRP, ADA, LINK, AVAX, DOGE, LTC, DOT, ATOM, TRX, NEAR (all `/USDT`).  
**Regime:** BTC/USDT.

### Protective checklist (order matters)

1. **Macro regime (200-EMA)** — BTC below 200-EMA → risk-off / prefer cash.  
2. **Fast regime for new buys** — BTC above ~50-EMA, RSI high enough, etc.  
3. **Equity lock (−15% from session peak)** — flatten; block until BTC reclaims.  
4. **Blow-off** — extreme RSI / stretch → block new alt entries.  
5. **Market shock** — BTC ~5-day return &lt; −8% → flatten until recovery.  
6. **Drift defense** — milder weakness → fewer/smaller entries.  
7. **Eligibility** — history, volume, own trend, positive momentum.  
8. **Score** ≈ avg(7d,14d,30d momentum) / 30d volatility.  
9. **Portfolio** — default **`max_positions = 1`**; rotate only after min hold + clear edge.  
10. **Heat** — shrink risk after ~−10% from in-market equity peak.

### Exits (typical defaults)

| Exit | Rule of thumb |
|---|---|
| Initial stop | Entry − **1.5 × ATR** |
| Trail | ~**2.0 × ATR** under highs |
| Take profit | ~**2.0 × ATR**; often sell a **portion**, leave a runner |
| Daily brake | ~**12%** paper loss in one UTC day → pause until next UTC day |

### Exchange vs paper display

- Orders hit **testnet**. Charts/history often use **public mainnet** (testnet history is empty).  
- Testnet faucet (~$10k) is **anchored** so UI paper equity stays near your ~$100 book.  
- **Idle cash** uses a **spot ledger** (`paper_cash_usdt`) that only changes on fills.  
- **Equity** = idle + open coins × mark. Marks move equity; they must **not** move idle cash.

---

## 7. Bot 2 — Gold (hourly breakout)

**UI:** Gold 1H Volatility Breakout  
**Code:** `gold_bot/strategy.py`, `gold_bot/live.py`

**Idea:** Wait for a volatility **squeeze**, then trade Donchian breakouts. Risk ~**0.9%** of the gold book. Exit on stop/trail/time (~48h).

### Data / loop

- Yahoo **`GC=F`**, 1h bars via `shared/feeds.py`.  
- Loop ~**180s**; decisions when a new hour completes.

### Entry sketch

1. Donchian 22 (shifted).  
2. ATR(14) vs slow ATR SMA(~50) → squeeze when ATR &lt; SMA.  
3. Breakout close outside channel with prior close inside.  
4. Long or short (unless `long_only`).

### Accounting

**CFD-style:** cash stays put on entry except **cost bps**; PnL added on exit. Adverse fill slip worsens the fill price.

---

## 8. Bot 3 — QQQ (15m opening range)

**UI:** QQQ 15m ORB  
**Code folder:** `mnq_bot/` (id stays `mnq` in URLs/files)

**Idea:** Build the first **15 minutes** of the US cash open (CET clock), trade breakouts with volume, **2:1** target, force flat by evening. Max **1** trade/day.

### Session (CET defaults)

| Phase | Time |
|---|---|
| Opening range | 15:30–15:45 |
| Entries | 15:45–18:00 |
| Force flat | from 21:00 |

### Sizing

Fractional QQQ shares; risk ~**0.5%** of cash vs stop distance; min notional filter.

---

## 9. Paper money, cash vs equity, fees

Defaults: `.env` + `paper/costs.py`.

### Capital

| Env | Default | Desk |
|---|---|---|
| `ORBIT_PAPER_EQUITY` | 100 | Crypto (+ default inheritance) |
| `GOLD_PAPER_EQUITY` | inherits | Gold |
| `MNQ_PAPER_EQUITY` | 100 | QQQ |

### Friction

| Desk | Default friction |
|---|---|
| Crypto | ≥ **10 bps** fee + **5 bps** slip / side (floors cheap testnet fees) |
| Gold | **2 bps** cost + **1 bps** adverse fill / side |
| QQQ | **1 bps** cost + **2 bps** adverse fill / side |

Fees are **approximate retail**, not a full broker simulator (no funding, margin calls, options, etc.).

### Crypto cash ledger (important)

```
Buy:  idle -= qty×price + fee + slip
Sell: idle += qty×price - fee - slip
Equity = idle + Σ(qty×mark)
Open PnL ≈ (mark−entry)×qty − leftover entry costs
```

If SOL’s mark ticks and idle moves, that is a **bug** (fixed by using the ledger, not `equity − mark`).

### Gold / QQQ

Cash moves mainly by **costs + realized PnL**. Open PnL shows in equity via mark-to-market on the equity curve.

---

## 10. Website, Start/Stop, Flatten

- URL: `http://HOST:8080`  
- Password: `ORBIT_DASHBOARD_PASSWORD` (default often `1234` — change it)

### Pages

| Path | Purpose |
|---|---|
| `/` | Platform: combined KPIs + three bot cards |
| `/crypto` | Full crypto desk |
| `/bot/gold`, `/bot/mnq` | Gold / QQQ desks |

### Start / Stop

- Starts enable `bot_enabled` and launch the loop.  
- Stops disable trading and stop the thread.

### Flatten desk / Flatten bot

1. Prompt asks for your **dashboard password** (not the word FLATTEN).  
2. Sells open lots (crypto on testnet; gold/QQQ close paper).  
3. **Pauses** the bot(s) so they do not reopen.  
4. Result message lists what sold vs “already flat.”  
5. Press **Start** again when you want trading to resume.

---

## 11. Telegram

Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, optional `TELEGRAM_DAILY_HOUR` (UTC).

**Immediate:** entries/exits (with desk equity block), crypto daily halt, order/system errors, deploys.  
**Daily digest:** day P&L, closed trades, opens, BTC regime line.

```bash
python -m orbit.notify --daily
```

---

## 12. Walk-forward research

Goal: reduce curve-fitting.

1. Train on window A → pick params.  
2. Test on next untouched window B.  
3. Roll forward; stitch OOS path.  
4. Fixed **gates** → ACCEPTED or not.

Artifacts:

- Heavy JSON: `backtest_output/` (local; not for tiny VMs)  
- UI snapshot: `research/walk_forward_summary.json`  
- Builder: `scripts/build_walk_forward_summary.py`

```bash
python scripts/run_walk_forward.py
python scripts/run_walk_forward_gold.py
python scripts/run_walk_forward_mnq.py
python scripts/build_walk_forward_summary.py
```

**Do not** run heavy walk-forwards on a 1 GB Always Free VM.

Snapshot headlines are **research**, not live Telegram P&L. Tiny trade counts (e.g. ORB) deserve skepticism.

---

## 13. Running locally and on the VM

### Local

```bash
python -m venv .venv
# activate
pip install -r requirements.txt
cp .env.example .env   # Binance testnet + optional Telegram
python run.py
```

Open `http://127.0.0.1:8080`. Without `ORBIT_AUTOSTART=1`, start bots from the UI.

### Binance testnet keys

Only from **https://testnet.binance.vision/** — normal Binance.com keys will not work.

### Oracle Cloud VM

See `deploy/README.md`. Typical layout: `/opt/orbit`, systemd `orbit.service`, `ORBIT_AUTOSTART=1`, port 8080, secrets only in `.env`.

---

## 14. Failure modes and safety

| Symptom | Likely cause |
|---|---|
| Telegram “Failed to fetch bot data” + Binance URL | Often **clock skew (−1021)**; NTP should fix; retries next loop |
| Gold/QQQ “running” but 0 trades forever | `bot_enabled: false` while thread alive |
| Crypto “idle” but holding SOL | `max_positions=1` — it **is** in a trade; waits for stop/rotate/daily bar |
| Position vanished after an API error | Old bug wiped state on failed sync — fixed to **preserve** open lots |
| Flatten → everything idle | By design (paused); Start to resume |
| Weekend QQQ silence | Markets closed / no new 15m bars |

Crypto failed fetches must **never** clear `positions` when no book is passed into `_sync_state`.

---

## 15. Honest limitations

1. Crypto = **testnet**, not production brokerage.  
2. Gold/QQQ = **local paper**, Yahoo can be delayed/gappy.  
3. Gold “ounces” ≠ COMEX contracts.  
4. QQQ fractions may not match every broker’s rules.  
5. ACCEPTED research ≠ promise.  
6. UI edits to `settings.json` can drift from research defaults.  
7. Fee models are approximate.  
8. Bar-based stops ≠ true intrabar fills.

Orbit’s job: a **clear reference** — “If I followed these rules with small money and honest friction, what would happen?”

---

## 16. Glossary

| Term | Meaning |
|---|---|
| USDT | Dollar-pegged stablecoin; UI money label |
| Spot | Own the asset (not a perpetual) |
| Notional | qty × price |
| bps | 0.01% (10 bps = 0.10%) |
| Drawdown | Fall from a prior equity peak |
| Regime | Broad risk-on / risk-off climate |
| ORB | Opening Range Breakout |
| OOS | Out-of-sample |
| Gate | Pass/fail walk-forward check |
| Idle cash | Money not spent on fills (crypto ledger) |
| Equity | Idle + marked open exposure |

---

## 17. Code index

| Topic | Start here |
|---|---|
| Crypto decision order | `orbit/strategy.py` |
| Crypto live loop | `orbit/engine.py` |
| Binance orders | `orbit/execution.py` |
| Crypto cash ledger / sync | `orbit/engine.py` (`paper_cash`, `_sync_state`) |
| Dashboard export | `orbit/exporter.py` |
| Telegram | `orbit/notify.py` |
| Gold rules / live | `gold_bot/strategy.py`, `gold_bot/live.py` |
| QQQ rules / live | `mnq_bot/strategy.py`, `mnq_bot/live.py` |
| Fees | `paper/costs.py` |
| Flatten | `paper/flatten.py` |
| Yahoo feeds | `shared/feeds.py` |
| Website | `webapp/server.py`, `webapp/templates/` |
| Crypto walk-forward | `backtest/walk_forward.py`, `scripts/run_walk_forward.py` |
| Deploy | `deploy/README.md`, `deploy/orbit.service` |

---

*Aligned with the paper desk defaults (~$100/bot, retail-like friction, password-confirmed flatten, spot cash ledger, QQQ desk in `mnq_bot/`, ACCEPTED research snapshot). Changing `.env` or settings changes behavior.*
