#!/usr/bin/env bash
# Install Orbit on Oracle Linux 9 or Ubuntu (Always Free Ampere).
set -euo pipefail

REPO_URL="${1:-}"
BRANCH="${ORBIT_BRANCH:-main}"
INSTALL_DIR="${ORBIT_HOME:-/opt/orbit}"
SERVICE_USER="${ORBIT_USER:-orbit}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/install.sh <git-clone-url>"
  exit 1
fi
if [[ -z "$REPO_URL" ]]; then
  echo "Usage: sudo bash deploy/install.sh git@github.com:YOU/orbit.git"
  echo "   or: sudo bash deploy/install.sh https://github.com/YOU/orbit.git"
  exit 1
fi

install_packages() {
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-pip python3-devel git curl ca-certificates firewalld
    dnf install -y python3-virtualenv || true
  elif command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y python3 python3-venv python3-pip git curl ca-certificates iptables-persistent
  else
    echo "Need dnf (Oracle Linux) or apt-get (Ubuntu)."
    exit 1
  fi
}

open_http_port() {
  if command -v firewall-cmd >/dev/null 2>&1; then
    systemctl enable --now firewalld || true
    firewall-cmd --permanent --add-port=8080/tcp || true
    firewall-cmd --reload || true
  fi
  if command -v iptables >/dev/null 2>&1; then
    iptables -C INPUT -p tcp --dport 8080 -j ACCEPT 2>/dev/null \
      || iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8080 -j ACCEPT || true
    if command -v netfilter-persistent >/dev/null 2>&1; then
      netfilter-persistent save || true
    fi
  fi
}

ensure_swap() {
  # Always Free AMD micro VMs have 1 GB RAM; pandas needs a swap file.
  if swapon --show | grep -q .; then
    return 0
  fi
  local mem_kb
  mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
  if [[ "${mem_kb:-0}" -ge 3000000 ]]; then
    return 0
  fi
  echo "Low RAM detected — creating 2G swap file."
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
}

install_packages
ensure_swap

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$INSTALL_DIR"
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
else
  git -C "$INSTALL_DIR" fetch origin
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
fi

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  echo "Created $INSTALL_DIR/.env — edit Binance + Telegram keys before starting."
fi
if ! grep -q '^ORBIT_DASHBOARD_PASSWORD=' "$INSTALL_DIR/.env"; then
  printf '\nORBIT_DASHBOARD_PASSWORD=1234\n' >> "$INSTALL_DIR/.env"
fi
# Secrets stay on the VM only; never world-readable.
chmod 600 "$INSTALL_DIR/.env"

install -m 644 "$INSTALL_DIR/deploy/orbit.service" /etc/systemd/system/orbit.service
install -m 644 "$INSTALL_DIR/deploy/orbit-update.service" /etc/systemd/system/orbit-update.service
install -m 644 "$INSTALL_DIR/deploy/orbit-update.timer" /etc/systemd/system/orbit-update.timer
chmod +x "$INSTALL_DIR/deploy/update.sh" "$INSTALL_DIR/deploy/install.sh"

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/.env"
chmod 755 "$INSTALL_DIR/deploy/update.sh"

INVOKER="${SUDO_USER:-opc}"
printf '%s ALL=(root) NOPASSWD: /opt/orbit/deploy/update.sh\n' "$INVOKER" \
  > /etc/sudoers.d/orbit-update
chmod 440 /etc/sudoers.d/orbit-update

open_http_port

systemctl daemon-reload
systemctl enable --now orbit.service
systemctl enable --now orbit-update.timer

PUB_IP="$(curl -4 -s --max-time 5 https://ifconfig.me || true)"
echo
echo "Orbit installed."
echo "  SSH user is usually: opc   (Oracle Linux)  or  ubuntu  (Ubuntu)"
echo "  1. sudo nano $INSTALL_DIR/.env   # Binance + Telegram"
echo "  2. sudo systemctl restart orbit"
echo "  3. Open VCN security list for TCP 22 and TCP 8080"
echo "  4. Website: http://${PUB_IP:-YOUR_VM_IP}:8080"
echo "     Password: value of ORBIT_DASHBOARD_PASSWORD in .env"
echo "  Logs: journalctl -u orbit -f"
echo "  Note: $INSTALL_DIR/.env is chmod 600 and is not updated by git pulls."
