# Host Orbit on Oracle Cloud (Always Free)

The VM runs Orbit 24/7. The website is public at `http://YOUR_VM_IP:8080` and asks for password **1234**. GitHub pushes update the VM automatically.

---

## A. Create the VM (Oracle Console)

Oracle Linux 9 is fine. **Do not click Create** until these two are fixed:

| Setting | Your form now | Change to |
|---|---|---|
| **Public IPv4 address** | No | **Yes** — assign a public IPv4 address |
| **SSH keys** | empty (`-`) | **Generate a key pair** → **Save private key** |

Leave the rest as you have it (name `orbit`, compartment root, AD-1, Ampere A1 Flex, Oracle Linux 9). 1 OCPU / 6 GB is enough.

**Germany Central (Frankfurt) often has zero Ampere capacity.** If every AD says “Out of capacity” for `VM.Standard.A1.Flex`, use Always Free **`VM.Standard.E2.1.Micro`** instead (1 GB RAM; the installer adds swap). You cannot move Always Free Ampere to another region; the home region is fixed at signup.

**Public IP stays greyed out unless the subnet is public.** If you do not see **Start VCN Wizard**, create the network by hand first (section A2), then create the instance and **Select existing** VCN + public subnet.

Then **Create**. Wait until **Running**. Copy the **Public IP**. SSH user is **`opc`**, not ubuntu.

### A2. Public VCN by hand (no wizard)

1. **☰ → Networking → Virtual Cloud Networks → Create VCN**
   - Name: `orbit-web`
   - IPv4 CIDR: `10.0.0.0/16`
   - DNS label: `orbitweb` (letters only, no hyphen)
   - IPv6: off
   - Create
2. Open that VCN → **Internet Gateways → Create Internet Gateway**
   - Name: `orbit-igw`
   - Enabled: yes
3. Still in the VCN → **Route Tables → Default Route Table** → **Add Route Rules**
   - Target type: **Internet Gateway**
   - Destination CIDR: `0.0.0.0/0`
   - Target: `orbit-igw`
4. VCN → **Subnets → Create Subnet**
   - Name: `public-orbit`
   - CIDR: `10.0.0.0/24`
   - Subnet access: **Public**
   - Route table: the default one you just edited
   - Create
5. Now **Create instance** → Networking: **Select existing VCN** `orbit-web` → **Select existing subnet** `public-orbit` → **Automatically assign public IPv4 address**.

---

## B. Open port 8080 (required or the site will not load)

Oracle blocks 8080 until you add a rule.

1. On the instance page, under **Primary VNIC**, click the **Subnet** name.
2. Click **Security Lists**.
3. Click **Default Security List for …**.
4. **Add Ingress Rules**.
5. Fill **exactly**:
   - Stateless: **unchecked**
   - Source Type: **CIDR**
   - Source CIDR: **`0.0.0.0/0`**
   - IP Protocol: **TCP**
   - Destination Port Range: **`8080`**
   - Description: `Orbit web`
6. **Add Ingress Rules**.

If the instance also shows **Network security groups**, open that NSG and add the same TCP 8080 ingress from `0.0.0.0/0`.

---

## C. Telegram bot (on your phone)

1. Telegram → search **@BotFather** → `/newbot` → copy the token.
2. Open a chat with your new bot and send `hello`.
3. In a browser open (paste your token):

   `https://api.telegram.org/botYOUR_TOKEN/getUpdates`

4. Copy the number in `"chat":{"id": 123456789 }`.

---

## D. Put this code on GitHub (on your PC)

In the Orbit folder:

```powershell
git add .
git commit -m "Cloud hosting, login password, Telegram alerts"
git branch -M main
git remote add origin https://github.com/YOURUSER/orbit.git
git push -u origin main
```

Use your real GitHub repo URL. Private repo is fine.

---

## E. Install on the VM (PowerShell on your PC)

Replace `PATH\TO\ssh-key.key` and `YOUR_VM_IP`.

```powershell
ssh -i PATH\TO\ssh-key.key opc@YOUR_VM_IP
```

The first time it asks `Are you sure you want to continue connecting?` type `yes`.

Then on the VM:

### If the GitHub repo is private

```bash
sudo ssh-keygen -t ed25519 -f /root/.ssh/orbit_github -N ""
sudo tee /root/.ssh/config >/dev/null <<'EOF'
Host github.com
  IdentityFile /root/.ssh/orbit_github
  StrictHostKeyChecking accept-new
EOF
sudo cat /root/.ssh/orbit_github.pub
```

Copy that public key → GitHub repo → **Settings → Deploy keys → Add deploy key** (read-only).

### Install

```bash
git clone git@github.com:YOURUSER/orbit.git ~/orbit-src
sudo bash ~/orbit-src/deploy/install.sh git@github.com:YOURUSER/orbit.git
sudo nano /opt/orbit/.env
```

In `.env` set (no quotes):

```
BINANCE_API_KEY=...
BINANCE_SECRET_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ORBIT_DASHBOARD_PASSWORD=1234
```

Save: `Ctrl+O`, Enter, `Ctrl+X`.

```bash
sudo systemctl restart orbit
```

You should get **Orbit · online** in Telegram.

---

## F. Open the website from any laptop

Browser:

```
http://YOUR_VM_IP:8080
```

Password: **`1234`**

Use `http` not `https`. Sign out is in the header.

---

## G. Auto-update when you push to GitHub

Already running on the VM: every 5 minutes it pulls `main` and restarts if needed. Telegram gets **Orbit · updated**.

For instant deploys, in GitHub → **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `OCI_HOST` | the VM public IP |
| `OCI_USER` | `opc` |
| `OCI_SSH_KEY` | full text of the **private** instance SSH key (`-----BEGIN …`) |

Then every `git push` to `main` updates the cloud.

---

## If the site does not open

1. Security list TCP **8080** from `0.0.0.0/0` (section B).
2. `sudo systemctl status orbit` — must be **active (running)**.
3. `sudo journalctl -u orbit -n 50 --no-pager`
4. Re-open the VM firewall: `sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8080 -j ACCEPT`

## Useful commands

```bash
sudo systemctl status orbit
sudo journalctl -u orbit -f
sudo systemctl restart orbit
sudo /opt/orbit/deploy/update.sh
```
