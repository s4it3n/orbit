#!/usr/bin/env bash
# One-time: turn /opt/orbit into a git checkout so update.sh / GitHub Actions work.
# Preserves .env, .venv, and gitignored ledger/state JSON.
set -euo pipefail

INSTALL_DIR="${ORBIT_HOME:-/opt/orbit}"
REPO_URL="${ORBIT_REPO:-https://github.com/s4it3n/orbit.git}"
BRANCH="${ORBIT_BRANCH:-main}"
SERVICE_USER="${ORBIT_USER:-orbit}"

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

if [[ ! -d "$INSTALL_DIR" ]]; then
  echo "Missing $INSTALL_DIR — run install.sh first"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Installing git..."
  dnf install -y git
fi

tmpdir="$(mktemp -d /tmp/orbit-git.XXXXXX)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT

echo "Cloning $REPO_URL ($BRANCH)..."
git clone --depth 50 --branch "$BRANCH" "$REPO_URL" "$tmpdir/src"

if [[ -f "$INSTALL_DIR/.env" ]]; then
  echo "Keeping existing .env"
fi

rm -rf "$INSTALL_DIR/.git"
cp -a "$tmpdir/src/.git" "$INSTALL_DIR/.git"
cd "$INSTALL_DIR"
git reset --hard "origin/$BRANCH" || git reset --hard HEAD

chmod +x "$INSTALL_DIR/deploy/update.sh" "$INSTALL_DIR/deploy/install.sh" \
  "$INSTALL_DIR/deploy/bootstrap_git.sh" || true

install -m 644 "$INSTALL_DIR/deploy/orbit-update.service" /etc/systemd/system/orbit-update.service
install -m 644 "$INSTALL_DIR/deploy/orbit-update.timer" /etc/systemd/system/orbit-update.timer
systemctl daemon-reload
systemctl enable --now orbit-update.timer

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
if [[ -f "$INSTALL_DIR/.env" ]]; then
  chmod 600 "$INSTALL_DIR/.env"
fi

echo "Git checkout ready at $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
systemctl list-timers --all | grep orbit-update || true
echo "Test: sudo $INSTALL_DIR/deploy/update.sh"
