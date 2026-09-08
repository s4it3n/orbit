#!/usr/bin/env bash
# Pull the latest GitHub main and restart Orbit if the tree changed.
# Prefer git when available; otherwise use the public GitHub tarball
# (fits Always Free micros that struggle with `dnf install git`).
set -euo pipefail

INSTALL_DIR="${ORBIT_HOME:-/opt/orbit}"
BRANCH="${ORBIT_BRANCH:-main}"
SERVICE_USER="${ORBIT_USER:-orbit}"
REPO_SLUG="${ORBIT_REPO_SLUG:-s4it3n/orbit}"

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

cd "$INSTALL_DIR"

mark_old_revision() {
  if [[ -d .git ]] && command -v git >/dev/null 2>&1; then
    git rev-parse HEAD 2>/dev/null || echo "unknown"
  elif [[ -f .orbit_deploy_rev ]]; then
    cat .orbit_deploy_rev
  else
    echo "none"
  fi
}

resolve_remote_sha() {
  curl -fsSL "https://api.github.com/repos/${REPO_SLUG}/commits/${BRANCH}" \
    | sed -n 's/.*"sha": "\([0-9a-f]\{40\}\)".*/\1/p' | head -1
}

update_via_git() {
  git fetch origin "$BRANCH"
  git reset --hard "origin/$BRANCH"
  git rev-parse HEAD
}

sync_tarball_tree() {
  local sha="$1"
  local tmp url root
  tmp="$(mktemp -d /tmp/orbit-upd.XXXXXX)"
  url="https://codeload.github.com/${REPO_SLUG}/tar.gz/${sha}"
  echo "Downloading ${url}" >&2
  curl -fsSL "$url" -o "$tmp/src.tgz"
  mkdir -p "$tmp/extract"
  tar -xzf "$tmp/src.tgz" -C "$tmp/extract"
  root="$(find "$tmp/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
  rsync -a \
    --exclude '.env' \
    --exclude '.venv/' \
    --exclude '.git/' \
    --exclude '.orbit_deploy_rev' \
    --exclude 'bot_state.json' \
    --exclude 'settings.json' \
    --exclude 'orbit_state.json' \
    --exclude 'gold_state.json' \
    --exclude 'mnq_state.json' \
    --exclude 'gold_live.json' \
    --exclude 'mnq_live.json' \
    --exclude 'gold_settings.json' \
    --exclude 'mnq_settings.json' \
    --exclude 'desk_daily.json' \
    --exclude 'data_cache/' \
    --exclude '__pycache__/' \
    "$root"/ "$INSTALL_DIR"/
  printf '%s\n' "$sha" > "$INSTALL_DIR/.orbit_deploy_rev"
  rm -rf "$tmp"
}

old="$(mark_old_revision)"

if [[ -d .git ]] && command -v git >/dev/null 2>&1; then
  echo "Updating via git..."
  new="$(update_via_git)"
else
  echo "Updating via GitHub tarball (no local git)..."
  if ! command -v curl >/dev/null 2>&1 || ! command -v rsync >/dev/null 2>&1 || ! command -v tar >/dev/null 2>&1; then
    echo "Need curl, tar, and rsync on the host for tarball updates"
    exit 1
  fi
  new="$(resolve_remote_sha)"
  if [[ -z "$new" ]]; then
    echo "Could not resolve ${BRANCH} SHA from GitHub API"
    exit 1
  fi
  if [[ "$old" == "$new" ]]; then
    echo "Already up to date ($new)"
    exit 0
  fi
  sync_tarball_tree "$new"
fi

if [[ "$old" == "$new" ]]; then
  echo "Already up to date ($new)"
  exit 0
fi

echo "Updating $old -> $new"
if [[ -f "$INSTALL_DIR/.env" ]]; then
  chmod 600 "$INSTALL_DIR/.env"
fi
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
install -m 644 "$INSTALL_DIR/deploy/orbit.service" /etc/systemd/system/orbit.service
systemctl daemon-reload
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
if [[ -f "$INSTALL_DIR/.env" ]]; then
  chmod 600 "$INSTALL_DIR/.env"
fi
chmod +x "$INSTALL_DIR/deploy/update.sh" "$INSTALL_DIR/deploy/install.sh" || true
[[ -f "$INSTALL_DIR/deploy/bootstrap_git.sh" ]] && chmod +x "$INSTALL_DIR/deploy/bootstrap_git.sh" || true

# Keep the 5-minute fallback timer wired if unit files exist.
if [[ -f "$INSTALL_DIR/deploy/orbit-update.timer" ]]; then
  install -m 644 "$INSTALL_DIR/deploy/orbit-update.service" /etc/systemd/system/orbit-update.service
  install -m 644 "$INSTALL_DIR/deploy/orbit-update.timer" /etc/systemd/system/orbit-update.timer
  systemctl daemon-reload
  systemctl enable --now orbit-update.timer || true
fi

systemctl restart orbit.service

branch_name="$BRANCH"
if [[ -d .git ]] && command -v git >/dev/null 2>&1; then
  branch_name="$(git rev-parse --abbrev-ref HEAD)"
fi
sudo -u "$SERVICE_USER" env PYTHONPATH="$INSTALL_DIR" \
  "$INSTALL_DIR/.venv/bin/python" -m orbit.notify --deploy "$new" "$branch_name" \
  || true

echo "Orbit restarted at $new"
