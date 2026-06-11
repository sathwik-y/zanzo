# Deploying Zanzo on a single EC2 box

The cheapest reliable setup: **one `t4g.small`** (2 vCPU / 2 GB, ARM) running the
entire backend stack in Docker — Postgres, Redis, MinIO, API, worker, poller,
engagement, and a Caddy TLS edge. The dashboard deploys separately (Vercel free
tier) and talks to the API over HTTPS.

```
 app.yourdomain.com  ──▶ Vercel (zanzo-fe, BACKEND_URL=https://api.yourdomain.com)
 api.yourdomain.com  ──▶ EC2: Caddy ──▶ api:8000
 media.yourdomain.com ─▶ EC2: Caddy ──▶ minio:9000   (presigned media URLs)
```

## Cost

| Item | Monthly |
|---|---|
| t4g.small on-demand (≈$0.0112/h, region-dependent) | ~$8.50 |
| 20 GB gp3 EBS | ~$1.60 |
| Vercel hobby + Deepgram/Gemini free tiers | $0 |
| **Total** | **~$10** |

`t4g.small` is periodically **free-tier eligible** (750 h/mo trial) — check the
launch wizard; if the badge is there, compute is $0 while the trial lasts.
**Stretch credits further:** a stopped instance only pays for EBS (~$1.60/mo).
Poller state lives in Postgres and IG sessions persist to disk, so
stop/start is safe — run the box only when you need it.

## Launch

1. **Instance:** Amazon Linux 2023 (**64-bit Arm**), `t4g.small`, 20 GB gp3.
   Security group: inbound 22 (your IP only), 80, 443. Nothing else — Postgres,
   Redis, MinIO and the raw API bind to loopback inside the box.
2. **DNS:** A records for `api.` and `media.` pointing at the instance's public
   IP. (Do this before starting Caddy so certificate provisioning succeeds.)
3. **Base setup** (as `ec2-user`):

```bash
# swap: 2 GB of headroom so a busy worker never OOMs the box
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# docker
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user   # re-login after this
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose --create-dirs && \
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

git clone https://github.com/sathwik-y/zanzo.git && cd zanzo
cp .env.example .env
```

4. **`.env` essentials for production:**

```ini
IG_SESSIONID=...                  # or manage bots from the admin panel instead
GEMINI_API_KEY=...
DEEPGRAM_API_KEY=...              # strongly recommended on a 2 GB box (skips local Whisper)
API_KEY=<openssl rand -hex 32>    # service key — must not stay "change-me"
JWT_SECRET=<openssl rand -hex 32>
ADMIN_EMAILS=you@example.com
API_DOMAIN=api.yourdomain.com
MEDIA_DOMAIN=media.yourdomain.com
S3_PUBLIC_ENDPOINT_URL=https://media.yourdomain.com
FRONTEND_ORIGIN=https://app.yourdomain.com
```

5. **Start everything** (migrations run automatically before the API):

```bash
docker compose --profile app --profile edge up -d --build
docker compose logs -f api   # watch for "Application startup complete"
```

6. **Dashboard:** import `zanzo-fe` into Vercel, set one env var —
   `BACKEND_URL=https://api.yourdomain.com` — and assign `app.yourdomain.com`.

7. **First account:** sign up with an email in `ADMIN_EMAILS` → you're admin.
   Add bot accounts (or rely on the `.env` one), link your Instagram, done.

## Operations

- **Update:** `git pull && docker compose --profile app --profile edge up -d --build`
- **Backup:** `docker compose exec postgres pg_dump -U recall recall | gzip > backup.sql.gz`
  (cron it and copy off-box; media in MinIO is re-fetchable but the DB isn't)
- **Stop when idle:** `docker compose stop` + stop the instance from the console.
  On start, services come back automatically (`restart: unless-stopped`).
- **Bot challenges:** the admin panel shows per-bot status; paste a fresh
  `sessionid` to reactivate a challenged bot.

## Caveats

- **Datacenter IP:** Instagram flags cloud IPs faster than residential ones.
  Keep the poll interval conservative and engagement caps low, especially the
  first weeks. The lowest-risk option remains running the poller at home and
  everything else on EC2 (`DATABASE_URL`/`REDIS_URL` over an SSH tunnel).
- **2 GB is sized for Deepgram transcription.** If you must run local Whisper,
  use `WHISPER_MODEL_SIZE=tiny` or move to a 4 GB instance (`t4g.medium`).
- **Spot instances:** not recommended here — the DB lives on the box, and a
  spot reclaim takes your archive down until you manually relaunch.
