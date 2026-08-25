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

## D. Updates

`orbit-update.timer` pulls `main` every 5 minutes. `/opt/orbit/.env` is not in git, so pulls do not overwrite keys.

For instant deploys, set GitHub Actions secrets `OCI_HOST`, `OCI_USER` (`opc`), `OCI_SSH_KEY` (private key text).

---

## Useful commands

```bash
sudo systemctl status orbit
sudo journalctl -u orbit -f
sudo systemctl restart orbit
sudo /opt/orbit/deploy/update.sh
```
