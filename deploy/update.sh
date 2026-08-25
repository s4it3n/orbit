#!/usr/bin/env bash
# Pull the latest GitHub commit and restart Orbit if the tree changed.
set -euo pipefail

INSTALL_DIR="${ORBIT_HOME:-/opt/orbit}"
BRANCH="${ORBIT_BRANCH:-main}"
SERVICE_USER="${ORBIT_USER:-orbit}"

cd "$INSTALL_DIR"

if [[ ! -d .git ]]; then
  echo "No git checkout at $INSTALL_DIR"
  exit 1
fi

old="$(git rev-parse HEAD)"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"
new="$(git rev-parse HEAD)"

if [[ "$old" == "$new" ]]; then
  echo "Already up to date ($new)"
  exit 0
fi

echo "Updating $old -> $new"
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/deploy/update.sh" "$INSTALL_DIR/deploy/install.sh" || true

systemctl restart orbit.service

branch_name="$(git rev-parse --abbrev-ref HEAD)"
sudo -u "$SERVICE_USER" env PYTHONPATH="$INSTALL_DIR" \
  "$INSTALL_DIR/.venv/bin/python" -m orbit.notify --deploy "$new" "$branch_name" \
  || true

echo "Orbit restarted at $new"
