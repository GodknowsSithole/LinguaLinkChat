# Deploying LinguaLink to a Google Compute Engine VM

This guide hosts the app with `docker-compose.prod.yml` (PostgreSQL + API + Next.js + Caddy for HTTPS)
on a Google Cloud VM, using **Google Cloud Translation** (`TRANSLATION_PROVIDER=google`) so the large
NLLB model is never loaded at runtime.

## Sizing and cost

| Option | Shape | RAM | Approx. cost | Notes |
|---|---|---|---|---|
| Free tier | `e2-micro` (us-west1 / us-central1 / us-east1 only) | 1 GB | Free (within Always Free limits) | Needs swap; builds are slow and may fail. See "Running on e2-micro". |
| Recommended | `e2-medium` | 4 GB | ~US$25/month | Builds and runs comfortably. |
| Minimum paid | `e2-small` | 2 GB | ~US$13/month | Works with 2 GB swap. |

Disk: use at least **30 GB** standard persistent disk. The API image still installs CPU PyTorch
(`backend/Dockerfile`), which makes the image several GB even though Google mode doesn't use it.

You also need a Google Cloud project with **billing enabled**.

---

## Step 1: Enable the APIs

In the Cloud Console (or Cloud Shell):
```bash
gcloud services enable compute.googleapis.com translate.googleapis.com
```

## Step 2: Restrict your Translation API key

Console -> **APIs & Services -> Credentials** -> your key:
- **API restrictions:** restrict to **Cloud Translation API**.
- **Application restrictions:** once you have the VM's static IP (Step 4), restrict to that IP address.
- Set a **Billing budget alert** (Billing -> Budgets & alerts), since the app has no rate limiting yet.

## Step 3: Create the VM

Console -> **Compute Engine -> VM instances -> Create instance**:
- **Name:** `lingualink-vm`
- **Region:** pick one near your users (for the free tier: `us-central1`, `us-west1` or `us-east1`).
- **Machine type:** `e2-medium` (or see the table above).
- **Boot disk:** Ubuntu 22.04 LTS, Standard persistent disk, 30 GB.
- **Firewall:** tick **Allow HTTP traffic** and **Allow HTTPS traffic**.

Or with gcloud:
```bash
gcloud compute instances create lingualink-vm \
  --zone=us-central1-a --machine-type=e2-medium \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --tags=http-server,https-server
```
The `http-server` / `https-server` tags use GCP's default rules for ports 80 and 443. If your network has
no such rules, create them:
```bash
gcloud compute firewall-rules create allow-http  --allow=tcp:80  --target-tags=http-server
gcloud compute firewall-rules create allow-https --allow=tcp:443 --target-tags=https-server
```
Unlike Oracle Cloud, Ubuntu on GCP has no extra iptables rules, so no VM-level firewall changes are needed.

## Step 4: Reserve a static IP

A VM's ephemeral IP changes when it is stopped, which would break your domain.
Console -> **VPC network -> IP addresses -> Reserve external static address**, then attach it to the VM
(VM -> Edit -> Network interfaces -> External IPv4 address). Or:
```bash
gcloud compute addresses create lingualink-ip --region=us-central1
gcloud compute instances delete-access-config lingualink-vm --zone=us-central1-a --access-config-name="External NAT"
gcloud compute instances add-access-config lingualink-vm --zone=us-central1-a \
  --address=$(gcloud compute addresses describe lingualink-ip --region=us-central1 --format='value(address)')
```
(A static IP attached to a running VM is free; an unused reserved IP is billed.)

## Step 5: Get a domain name

Caddy needs a real domain for automatic HTTPS. Use [DuckDNS](https://www.duckdns.org) (free) or your own:
1. Create a subdomain, e.g. `lingualink-yourname.duckdns.org`.
2. Point it at the static IP from Step 4.
3. Confirm: `ping lingualink-yourname.duckdns.org` shows that IP.

## Step 6: Connect and install Docker

```bash
gcloud compute ssh lingualink-vm --zone=us-central1-a
```
(or click **SSH** next to the VM in the console). Then on the VM:
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
docker compose version
```

## Step 7: Get the project onto the VM

Push the project to a GitHub repo (make sure `.env` is NOT committed; it is git-ignored), then:
```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```
Or copy from Windows with gcloud:
```powershell
gcloud compute scp --recurse C:\sandbox\LinguaLinkChat lingualink-vm:~/LinguaLinkChat --zone=us-central1-a
```
(Delete `backend/.venv`, `frontend/node_modules` and `data/` locally first, or they will be copied too.)

## Step 8: Configure environment variables

```bash
cp .env.example .env
nano .env
```
Set:
```
JWT_SECRET=<output of: openssl rand -hex 32>
POSTGRES_PASSWORD=<output of: openssl rand -hex 24>
PUBLIC_DOMAIN=lingualink-yourname.duckdns.org
TRANSLATION_PROVIDER=google
GOOGLE_TRANSLATE_API_KEY=<your key>
```

## Step 9: Build and start

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
```
In Google mode the first message is not slow (no model download).

## Step 10: Test

Open `https://<your-domain>`. Register two users with different preferred languages in separate
browser profiles and confirm messages translate in real time.

## Restarts and backups

All services use `restart: unless-stopped`, so they come back after a reboot.

Backup:
```bash
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U lingualink lingualink > lingualink-$(date +%F).sql
tar -czf uploads-$(date +%F).tar.gz data/uploads
```
You can also schedule disk snapshots: Compute Engine -> Disks -> your disk -> **Create snapshot schedule**.

## Updating

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

## Running on e2-micro (1 GB, free tier)

Add swap before building:
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```
Build one service at a time to limit memory use:
```bash
docker compose -f docker-compose.prod.yml build api
docker compose -f docker-compose.prod.yml build web
docker compose -f docker-compose.prod.yml up -d
```
If the `web` build is killed (out of memory), build the images on a bigger temporary VM or your own
machine, or upgrade to `e2-small`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Site unreachable | Firewall rule or network tag missing | Check Step 3 tags/rules; VM must have `http-server` and `https-server` tags |
| HTTPS certificate error | `PUBLIC_DOMAIN` doesn't match DNS, or DNS not propagated | `ping` the domain, then `docker compose -f docker-compose.prod.yml restart proxy` |
| Domain stopped working after VM restart | Using an ephemeral IP | Reserve a static IP (Step 4) |
| Translations fail with 403 | Translation API or billing not enabled, or key restricted to the wrong IP | Recheck Steps 1-2 |
| Translation error "Set GOOGLE_TRANSLATE_API_KEY" | Key missing in the VM's `.env` | Fix `.env`, then `docker compose -f docker-compose.prod.yml up -d` |
| Build killed / out of memory | VM too small | Add swap or use `e2-medium` |
| Container keeps restarting | Bad `.env` | `docker compose -f docker-compose.prod.yml logs api` |
