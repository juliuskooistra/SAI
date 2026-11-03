# Deploying BikeShop on a VM

The runbook for SPEC §10. The target is an Ubuntu VM (22.04 or later) whose
**nginx already serves other sites on ports 80/443**. BikeShop runs in Docker
behind that nginx. The demo runs at <https://demo.sai1.airs.iadsf.ch>; replace
that hostname with yours everywhere below.

```text
internet ─443─► nginx (host, certbot) ──► 127.0.0.1:8130 (FastAPI: the API and the website)
```

Everything below runs on the VM (`ssh <your-server>`).

## 0. Before you start

- **DNS**: an A record for your hostname points at the VM.
  `dig +short demo.sai1.airs.iadsf.ch` must return the VM's IP.
- **Disk**: `df -h /` should show **at least 3 GB free**. Docker Engine and the
  two images take about 1.5 GB. Old package caches are usually the easiest
  to clear (`pip cache purge`, `sudo journalctl --vacuum-size=200M`).
- **Firewall**: only SSH, 80 and 443 open to the internet.

## 1. Install Docker (once)

Docker Engine + the compose plugin from Docker's own apt repository:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Cap container logs, so they can't fill the disk:

```bash
echo '{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}' \
  | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
sudo docker run --rm hello-world
```

## 2. Get the code

```bash
sudo git clone https://github.com/juliuskooistra/SAI.git /opt/sai
sudo chown -R $USER: /opt/sai
cd /opt/sai/Use_Case_BikeShop
```

## 3. Settings

```bash
cp .env.example .env && chmod 600 .env
nano .env
```

Fill in `API_KEY_SECRET` (random, see the comment), `MLMP_API_KEY` and the
date the key was created, `CORS_ORIGINS` (`https://` + your hostname), and the
two seed passwords.

## 4. Start

```bash
sudo docker compose up -d --build
sudo docker compose ps                        # api "healthy", worker "running"
curl -s 127.0.0.1:8130/health                 # "inference": "ok" means the VM reaches MLMP
sudo docker compose exec api python -m scripts.seed
```

## 5. nginx and HTTPS

```bash
sudo cp deploy/nginx/demo.sai1.airs.iadsf.ch.conf /etc/nginx/conf.d/
sudo nginx -t && sudo systemctl reload nginx   # never reload when -t fails: every site on the VM shares nginx
sudo certbot --nginx -d demo.sai1.airs.iadsf.ch
```

Most nginx installs load every file in `conf.d/` (`include /etc/nginx/conf.d/*.conf;`
in `nginx.conf`). If yours names each site instead, add an `include` line for
this file to the `http` block of `/etc/nginx/nginx.conf`. Otherwise the file is
copied but never loaded.

## 6. Check

```bash
curl -sI https://demo.sai1.airs.iadsf.ch | head -1              # 200, the website
curl -s https://demo.sai1.airs.iadsf.ch/health                  # the API
```

Also check that the other sites on the VM still answer. From outside, ports
8130 must refuse connections.

## Updating

```bash
cd /opt/sai && git pull
cd Use_Case_BikeShop && sudo docker compose up -d --build && sudo docker image prune -f
```

The data stays: it lives on the `bikeshop-data` volume.

## Rolling back

There are no versioned images. To roll back, check out the previous commit
(`git checkout <commit>`) and rebuild as above. If a release also changed data,
restore the volume from a copy (there are no automatic backups yet, see
[MAP.md](MAP.md)):

```bash
sudo docker compose cp api:/app/api/data/bikeshop.db ./bikeshop-$(date +%F).db   # manual copy before a risky update
```

## Logs and status

```bash
sudo docker compose logs -f api
sudo docker compose logs -f worker   # jobs (emails) and the reservation expiry
curl -s https://demo.sai1.airs.iadsf.ch/health
```

## Renewing the MLMP key (every 180 days)

When `/health` shows `"inference": "unauthorized"`, create a new key at
<https://access.mlmp.ti.bfh.ch>, put it in `.env` with the new date, and run
`sudo docker compose up -d` to restart with it.
