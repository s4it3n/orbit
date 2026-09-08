# Host Orbit on Oracle Cloud (Always Free)

The VM runs Orbit 24/7. The site is at `http://YOUR_VM_IP:8080`. Secrets stay in `/opt/orbit/.env` on the VM only — never in GitHub.

---

## A. Create the VM

| Setting | Value |
|---|---|
| Image | Oracle Linux 9 |
| Shape | Prefer `VM.Standard.A1.Flex` (Ampere). If every AD is out of capacity in Frankfurt, use Always Free **`VM.Standard.E2.1.Micro`**. |
| Networking | Existing public VCN/subnet, **assign public IPv4** |
| SSH key | Upload your public key |

SSH user is **`opc`**.

### Public VCN (if you do not have one)

1. Create VCN `orbit-web`, CIDR `10.0.0.0/16`, DNS label `orbitweb`
2. Create Internet Gateway + default route `0.0.0.0/0` → IGW
3. Create public subnet `public-orbit`, `10.0.0.0/24`
4. Security list ingress: TCP **22** and **8080** from `0.0.0.0/0`

---

## B. Install

On the VM:

```bash
sudo dnf install -y git
git clone https://github.com/YOURUSER/orbit.git ~/orbit-src
sudo bash ~/orbit-src/deploy/install.sh https://github.com/YOURUSER/orbit.git
```

Edit secrets (never commit this file):

```bash
sudo nano /opt/orbit/.env
```

```
BINANCE_API_KEY=...
BINANCE_SECRET_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ORBIT_DASHBOARD_PASSWORD=choose-a-strong-password
```

```bash
sudo systemctl restart orbit
```

Open `http://YOUR_VM_IP:8080`.

---

## C. Telegram chat ID

1. @BotFather → create bot → copy token  
2. Message your bot once  
3. Open `https://api.telegram.org/botYOUR_TOKEN/getUpdates`  
4. Copy `"chat":{"id": ...}`

---

## D. Updates (auto on push)

Pushes to `main` run `.github/workflows/deploy.yml`, which SSHs in and runs `sudo /opt/orbit/deploy/update.sh`.

`update.sh` pulls the tip of `main` via **git** if `/opt/orbit` is a checkout, otherwise via the **GitHub tarball** (no `git` package required — better for tiny Always Free VMs). `.env`, `.venv`, and ledger JSON are preserved.

Optional backup: enable `orbit-update.timer` (every 5 minutes). First successful `update.sh` enables it.

GitHub Actions secrets:

| Secret | Value |
|---|---|
| `OCI_HOST` | VM public IP |
| `OCI_USER` | `opc` |
| `OCI_SSH_KEY` | private SSH key text (same key that logs you in) |

Optional one-time git checkout (only if you want git-based pulls):

```bash
sudo bash /opt/orbit/deploy/bootstrap_git.sh
```

Requires `git` installed; skip this on micros that OOM during `dnf install git`.

---

## Useful commands

```bash
sudo systemctl status orbit
sudo journalctl -u orbit -f
sudo systemctl restart orbit
sudo /opt/orbit/deploy/update.sh
```
