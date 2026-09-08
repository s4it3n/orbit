#!/usr/bin/env bash
# Deploy working-tree code + scale paper books $1000 → $100 (keep trade history).
set -euo pipefail

ARCHIVE="${HOME}/orbit-deploy.tgz"
INSTALL=/opt/orbit

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Missing $ARCHIVE"
  exit 1
fi

sudo systemctl stop orbit.service || true

# Preserve secrets + live ledgers
sudo cp -a "$INSTALL/.env" /tmp/orbit.env.bak
for f in bot_state.json gold_live.json mnq_live.json settings.json \
         orbit_state.json gold_state.json mnq_state.json; do
  if [[ -f "$INSTALL/$f" ]]; then
    sudo cp -a "$INSTALL/$f" "/tmp/$f.bak"
  fi
done

TMP="$(mktemp -d)"
tar -xzf "$ARCHIVE" -C "$TMP"

if command -v rsync >/dev/null 2>&1; then
  sudo rsync -a \
    --exclude '.venv' \
    --exclude '.env' \
    --exclude 'data_cache' \
    --exclude 'backtest_output' \
    --exclude 'bot_state.json' \
    --exclude 'gold_live.json' \
    --exclude 'mnq_live.json' \
    --exclude 'settings.json' \
    --exclude 'orbit_state.json' \
    --exclude 'gold_state.json' \
    --exclude 'mnq_state.json' \
    "$TMP"/ "$INSTALL"/
else
  sudo cp -a "$TMP"/. "$INSTALL"/
fi
rm -rf "$TMP"

# Restore preserved live files (rsync shouldn't have touched them, but be safe)
sudo cp -a /tmp/orbit.env.bak "$INSTALL/.env"
for f in bot_state.json gold_live.json mnq_live.json settings.json; do
  if [[ -f "/tmp/$f.bak" ]]; then
    sudo cp -a "/tmp/$f.bak" "$INSTALL/$f"
  fi
done

# Paper equity → $100/bot
if sudo grep -q '^ORBIT_PAPER_EQUITY=' "$INSTALL/.env"; then
  sudo sed -i 's/^ORBIT_PAPER_EQUITY=.*/ORBIT_PAPER_EQUITY=100/' "$INSTALL/.env"
else
  echo 'ORBIT_PAPER_EQUITY=100' | sudo tee -a "$INSTALL/.env" >/dev/null
fi
# Drop optional overrides so they inherit 100
sudo sed -i '/^GOLD_PAPER_EQUITY=/d;/^MNQ_PAPER_EQUITY=/d' "$INSTALL/.env"

# Scale crypto paper display once (Gold/MNQ scale via _load below)
cd "$INSTALL"
sudo env PYTHONPATH="$INSTALL" "$INSTALL/.venv/bin/python" scripts/rescale_crypto_paper.py --old-cap 1000 --new-cap 100

# Force Gold/MNQ rescale now (don't wait for loop)
sudo env PYTHONPATH="$INSTALL" "$INSTALL/.venv/bin/python" <<'PY'
from gold_bot import live as gold_live
from mnq_bot import live as mnq_live
from paper import save_account

g = gold_live._load()
save_account(gold_live.ACCOUNT_PATH, g)
print("gold", g.get("initial_capital"), g.get("cash"), len(g.get("trades") or []))

m = mnq_live._load()
save_account(mnq_live.ACCOUNT_PATH, m)
print("mnq", m.get("initial_capital"), m.get("cash"), len(m.get("trades") or []))
PY

# Refresh exported state files
sudo rm -f "$INSTALL/orbit_state.json" "$INSTALL/gold_state.json" "$INSTALL/mnq_state.json"

sudo chown -R orbit:orbit "$INSTALL"
sudo chmod 600 "$INSTALL/.env"

sudo systemctl start orbit.service
sleep 10
sudo systemctl is-active orbit.service

# Verify books
sudo env PYTHONPATH="$INSTALL" "$INSTALL/.venv/bin/python" <<'PY'
import json
from pathlib import Path
root = Path("/opt/orbit")
for name in ["bot_state.json", "gold_live.json", "mnq_live.json"]:
    d = json.loads((root / name).read_text())
    if "initial_capital" in d:
        print(name, "initial", d["initial_capital"], "cash", round(float(d["cash"]), 2),
              "trades", len(d.get("trades") or []),
              "t0_qty", (d["trades"][0].get("quantity") if d.get("trades") else None),
              "t0_pnl", (d["trades"][0].get("pnl_usdt") if d.get("trades") else None))
    else:
        print(name, "paper_cap", d.get("paper_equity_cap"), "equity", round(float(d.get("equity_usdt") or 0), 2),
              "anchor", d.get("exchange_equity_anchor"))
PY

curl -sS -o /tmp/health.json -w "health %{http_code}\n" http://127.0.0.1:8080/api/health || true
