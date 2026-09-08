#!/usr/bin/env bash
set -euo pipefail
INSTALL=/opt/orbit
export PYTHONPATH="$INSTALL"

sudo systemctl stop orbit.service || true

# Prefer gold/mnq backups from before any scale
if [[ -f /tmp/gold_live.json.bak ]]; then
  sudo cp -a /tmp/gold_live.json.bak "$INSTALL/gold_live.json"
fi
if [[ -f /tmp/mnq_live.json.bak ]]; then
  sudo cp -a /tmp/mnq_live.json.bak "$INSTALL/mnq_live.json"
fi

if sudo grep -q '^ORBIT_PAPER_EQUITY=' "$INSTALL/.env"; then
  sudo sed -i 's/^ORBIT_PAPER_EQUITY=.*/ORBIT_PAPER_EQUITY=100/' "$INSTALL/.env"
else
  echo 'ORBIT_PAPER_EQUITY=100' | sudo tee -a "$INSTALL/.env" >/dev/null
fi
sudo sed -i '/^GOLD_PAPER_EQUITY=/d;/^MNQ_PAPER_EQUITY=/d' "$INSTALL/.env"

# Crypto: remap paper book to $100 while keeping the same % P&L vs the original $1000 book.
# Use exchange equity + known original faucet anchor (10000) when present.
sudo env PYTHONPATH="$INSTALL" "$INSTALL/.venv/bin/python" <<'PY'
import json
from pathlib import Path

STATE = Path("/opt/orbit/bot_state.json")
EXPORT = Path("/opt/orbit/orbit_state.json")
live = json.loads(STATE.read_text(encoding="utf-8"))

new_cap = 100.0
old_cap = 1000.0
exchange = float(live.get("exchange_equity_usdt") or 0.0)
# Original paper mapping used faucet baseline ~10000.
original_anchor = 10000.0
if exchange > 0:
    original_paper = old_cap + (exchange - original_anchor)
else:
    # Fallback: treat current equity as if it still represented the $1000 book.
    original_paper = float(live.get("equity_usdt") or old_cap)
    # If already mangled near 16, reconstruct from known ~62% gain snapshot.
    if original_paper < 200:
        original_paper = 1620.0472

scale = new_cap / old_cap
pnl = original_paper - old_cap
live["paper_equity_cap"] = new_cap
live["equity_usdt"] = new_cap + pnl * scale
if exchange > 0:
    live["exchange_equity_anchor"] = exchange - (float(live["equity_usdt"]) - new_cap)
for op in list(live.get("operations") or []):
    if op.get("pnl_usdt") is not None:
        # ops may already be unscaled; only scale if magnitudes look like $1000-era
        pass
STATE.write_text(json.dumps(live, indent=2, default=str), encoding="utf-8")
if EXPORT.exists():
    EXPORT.unlink()
print(
    "crypto",
    "exchange", exchange,
    "original_paper", original_paper,
    "cap", live["paper_equity_cap"],
    "equity", live["equity_usdt"],
    "anchor", live.get("exchange_equity_anchor"),
)
PY

sudo env PYTHONPATH="$INSTALL" "$INSTALL/.venv/bin/python" <<'PY'
from gold_bot import live as gold_live
from mnq_bot import live as mnq_live
from paper import save_account

g = gold_live._load()
save_account(gold_live.ACCOUNT_PATH, g)
t0 = (g.get("trades") or [None])[0]
print(
    "gold",
    g.get("initial_capital"),
    round(float(g.get("cash")), 4),
    "trades",
    len(g.get("trades") or []),
    "t0_qty",
    None if not t0 else t0.get("quantity"),
    "t0_pnl",
    None if not t0 else t0.get("pnl_usdt"),
)

m = mnq_live._load()
save_account(mnq_live.ACCOUNT_PATH, m)
t0 = (m.get("trades") or [None])[0]
print(
    "mnq",
    m.get("initial_capital"),
    round(float(m.get("cash")), 4),
    "trades",
    len(m.get("trades") or []),
    "t0_qty",
    None if not t0 else t0.get("quantity"),
    "t0_pnl",
    None if not t0 else t0.get("pnl_usdt"),
)
PY

sudo rm -f "$INSTALL/orbit_state.json" "$INSTALL/gold_state.json" "$INSTALL/mnq_state.json"
sudo chown -R orbit:orbit "$INSTALL"
sudo chmod 600 "$INSTALL/.env"
sudo systemctl start orbit.service
sleep 12
echo "service=$(sudo systemctl is-active orbit.service)"
sudo grep '^ORBIT_PAPER_EQUITY=' "$INSTALL/.env"

sudo env PYTHONPATH="$INSTALL" "$INSTALL/.venv/bin/python" <<'PY'
import json
from pathlib import Path

root = Path("/opt/orbit")
total = 0.0
for name in [
    "bot_state.json",
    "gold_live.json",
    "mnq_live.json",
    "orbit_state.json",
    "gold_state.json",
    "mnq_state.json",
]:
    p = root / name
    if not p.exists():
        print(name, "MISSING")
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    if "initial_capital" in d:
        cash = float(d.get("cash") or 0)
        print(name, "initial", d["initial_capital"], "cash", round(cash, 2), "trades", len(d.get("trades") or []))
        if name.endswith("_live.json"):
            total += cash
    else:
        eq = d.get("equity_usdt")
        print(name, "cap", d.get("paper_equity_cap"), "equity", None if eq is None else round(float(eq), 2))
        if name == "bot_state.json" and eq is not None:
            total += float(eq)
print("approx_desk", round(total, 2))
PY

curl -sS -o /tmp/health.json -w "health %{http_code}\n" http://127.0.0.1:8080/api/health || true
