# Deploying LinguaLink to a free Oracle Cloud VM

This guide walks through hosting the app as-is (PostgreSQL + in-process NLLB-200 model) on Oracle Cloud's
"Always Free" tier, which is the only free option with enough RAM (up to 24 GB) to comfortably run the
translation model, plus a persistent disk for the PostgreSQL data volume and uploaded attachments.

Total cost: **R0 / $0**, forever, as long as you stay within the Always Free limits (1–4 OCPUs, up to 24 GB
RAM, 200 GB block storage, one free-tier VM).

---

## Step 1 — Create an Oracle Cloud account

1. Go to https://www.oracle.com/cloud/free/ and sign up for an account (requires a credit card for
   identity verification only — Always Free resources are never billed).
2. Choose your home region carefully during signup — you cannot easily change it later, and Always Free
   Ampere (ARM) capacity is sometimes limited in busy regions. If a region is unavailable, try a
   nearby one (e.g. if `af-johannesburg-1` has no free Ampere capacity, `eu-frankfurt-1` or
   `uk-london-1` are good alternatives with more capacity).

## Step 2 — Create the VM instance

1. In the OCI Console, go to **Compute → Instances → Create Instance**.
2. **Name:** `lingualink-vm`.
3. **Image and shape:**
   - Click **Edit** next to "Image and shape".
   - Image: **Ubuntu 22.04** (Canonical Ubuntu).
   - Shape: click **Change shape**, select **Ampere** → **VM.Standard.A1.Flex**, and set
     **4 OCPUs / 24 GB memory** (the maximum Always Free allowance). If capacity is unavailable, try
     2 OCPUs / 12 GB, or retry later/in another region — Ampere Always Free capacity is popular.
4. **Networking:** keep the default VCN, or create a new one if this is your first instance. Ensure
   **"Assign a public IPv4 address"** is checked.
5. **Add SSH keys:** choose **Generate a key pair for me** and download the private key (`.key` file), or
   paste your own public key if you already have one (`ssh-keygen -t ed25519` on your machine, then paste
   the contents of `~/.ssh/id_ed25519.pub`).
6. Click **Create**. Wait a few minutes for the instance state to become **Running**, then note its
   **Public IP address**.

## Step 3 — Open the required firewall ports

Oracle Cloud has **two** firewalls to configure — the cloud-level Security List/NSG, and Ubuntu's own
`iptables`/`netfilter-persistent` rules (Oracle's Ubuntu images ship with restrictive default rules).

**3a. Cloud-level (Security List):**
1. Go to **Networking → Virtual Cloud Networks →** your VCN **→ Security Lists** → the default security list.
2. **Add Ingress Rules:**
   - Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port `80` (HTTP)
   - Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port `443` (HTTPS)
   - (Port 22/SSH is already open by default.)

**3b. VM-level (Ubuntu's iptables):** SSH into the machine first (see Step 4), then run:
```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## Step 4 — Connect to the VM

```bash
chmod 400 /path/to/downloaded-key.key
ssh -i /path/to/downloaded-key.key ubuntu@<YOUR_VM_PUBLIC_IP>
```

## Step 5 — Install Docker and Docker Compose

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
docker --version
docker compose version
```

## Step 6 — Get the project onto the VM

The simplest approach is to push the project to a GitHub repository first (from your own machine), then
clone it on the VM:

```bash
# On the VM:
git clone https://github.com/<your-username>/LinguaLink-Chat-SA.git
cd LinguaLink-Chat-SA
```

If you don't want to use GitHub, you can instead copy the folder directly from Windows using `scp`
(run this from your Windows machine, not the VM):
```powershell
scp -i C:\path\to\downloaded-key.key -r "C:\Users\sitho\Downloads\LinguaLink-Chat-SA\LinguaLink-Chat-SA" ubuntu@<YOUR_VM_PUBLIC_IP>:~/LinguaLink-Chat-SA
```

## Step 7 — Get a free domain name (needed for automatic HTTPS)

Let's Encrypt (used by Caddy for free HTTPS) needs a real domain name, not just a bare IP address.
[DuckDNS](https://www.duckdns.org) provides free subdomains:

1. Go to https://www.duckdns.org and sign in (GitHub/Google login).
2. Create a subdomain, e.g. `lingualink-yourname` → it becomes `lingualink-yourname.duckdns.org`.
3. Set its IP to your VM's public IP address and click **update**.
4. Confirm it resolves: `ping lingualink-yourname.duckdns.org` should show your VM's IP (may take a
   few minutes to propagate).

## Step 8 — Configure environment variables

```bash
cd ~/LinguaLink-Chat-SA
cp .env.example .env
nano .env
```
Set:
```
JWT_SECRET=<paste output of: openssl rand -hex 32>
POSTGRES_PASSWORD=<paste output of: openssl rand -hex 24>
PUBLIC_DOMAIN=lingualink-yourname.duckdns.org
```
Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

## Step 9 — Build and start the app

```bash
docker compose -f docker-compose.prod.yml up -d --build
```
The first build will take a while (downloading Python/Node dependencies and PyTorch/Transformers).
The **first message you send** will also take longer, since the NLLB-200 model (~2.5 GB) downloads
from Hugging Face on first use and is then cached in the `hf-cache` volume for all future runs.

Check everything started correctly:
```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f
```
(Press `Ctrl+C` to stop following logs — the containers keep running in the background.)

## Step 10 — Test it

Open `https://lingualink-yourname.duckdns.org` in your browser. Caddy automatically requested and
installed a free Let's Encrypt certificate on first request, so it should load over HTTPS with no
browser warnings. Register two accounts with different preferred languages (in separate browser
profiles/incognito windows) and confirm messages translate and arrive in real time.

## Step 11 — Keep it running automatically

Docker's `restart: unless-stopped` policy (already set in `docker-compose.prod.yml`) means all
containers restart automatically if the VM reboots or a container crashes, **as long as the Docker
daemon itself starts on boot**, which it does by default on Ubuntu after installation. No extra
systemd unit is required.

## Step 12 — Back up your data

The PostgreSQL data lives in the `pg-data` Docker volume and uploaded attachments in `./data/uploads`; both are safe across container
restarts/rebuilds. To back them up periodically:
```bash
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U lingualink lingualink > lingualink-$(date +%F).sql
tar -czf uploads-$(date +%F).tar.gz data/uploads
```
Copy the resulting `.tar.gz` off the VM (e.g. `scp` it back to your own machine) on whatever schedule
suits your project (weekly is reasonable for a final-year project demo environment).

---

## Updating the app after code changes

```bash
cd ~/LinguaLink-Chat-SA
git pull                       # if using GitHub
docker compose -f docker-compose.prod.yml up -d --build
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser can't reach the site at all | Security List or `iptables` port 80/443 not open | Recheck Step 3a and 3b |
| Certificate error / HTTP works but HTTPS doesn't | `PUBLIC_DOMAIN` in `.env` doesn't match the DNS record, or DNS hasn't propagated yet | Confirm `ping` resolves correctly first, then restart: `docker compose -f docker-compose.prod.yml restart proxy` |
| First translation is very slow or times out | Model still downloading on first request | Wait — subsequent requests will be fast once cached in the `hf-cache` volume |
| Container keeps restarting | Check logs: `docker compose -f docker-compose.prod.yml logs api` | Often a missing/invalid `JWT_SECRET` or `.env` typo |
| Out of memory during model load | Instance shape too small | Increase to 4 OCPU/24 GB in the OCI console (Instance → Edit shape), or reduce concurrent load |
