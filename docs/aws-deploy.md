# Deploying Recall to AWS

Recall runs locally by default. This guide maps each local service to its AWS equivalent. Expected cost at personal volume: **$20–30/month**.

## Service mapping

| Local (docker-compose) | AWS | Notes |
|---|---|---|
| postgres (pgvector/pgvector:pg16) | RDS PostgreSQL 16, `db.t4g.micro` | Enable the `vector` extension (supported on RDS since PG15) |
| minio | S3 bucket | Remove `S3_ENDPOINT_URL` from env; boto3 then targets real S3 |
| redis | ElastiCache `cache.t4g.micro`, or keep Redis on the EC2 box | Or implement the two-method `JobQueue` interface over SQS |
| api + worker + poller | One EC2 `t3.medium` running docker compose, or ECS | t3.medium handles polling + 2 workers + API comfortably |
| frontend | Vercel free tier, or the same EC2 box | Set `BACKEND_URL` + `BACKEND_API_KEY` env on the deployment |

## Steps (EC2 path, simplest)

1. **RDS:** create a PostgreSQL 16 instance, `db.t4g.micro`, 20GB. Create database `recall`. Run `CREATE EXTENSION vector;` as admin (the migration also attempts it).
2. **S3:** create a private bucket, e.g. `yourname-recall-media`. Create an IAM user with access limited to that bucket; note the keys.
3. **EC2:** launch `t3.medium` (Amazon Linux 2023 or Ubuntu), install Docker + compose plugin. Clone the repo.
4. **.env on the instance:**
   ```
   DATABASE_URL=postgresql+psycopg://recall:<password>@<rds-endpoint>:5432/recall
   S3_ENDPOINT_URL=            # empty = real S3
   S3_BUCKET=yourname-recall-media
   S3_ACCESS_KEY=...
   S3_SECRET_KEY=...
   REDIS_URL=redis://redis:6379/0
   API_KEY=<long random string>
   ```
5. **Run:** `docker compose --profile app up -d --build` (skip the postgres/minio services; point env at RDS/S3).
6. **Migrate:** `docker compose run --rm api alembic upgrade head`
7. **Frontend on Vercel:** import the `frontend/` directory, set `BACKEND_URL=https://<your-api-host>` and `BACKEND_API_KEY`. Put the API behind HTTPS (an ALB with ACM cert, or Caddy on the instance).

## The poller and IP reputation

Instagram flags datacenter IPs faster than residential ones. Two workable layouts:

- **Hybrid (recommended):** API + worker + dashboard on AWS; run only the poller at home (`python -m recall.services.poller` with `DATABASE_URL`/`REDIS_URL` pointing at AWS, Redis port exposed via security group to your home IP only or through a WireGuard tunnel).
- **All-AWS:** accept the elevated ban risk on the burner account. Keep the polling interval at 300s or higher.

## Whisper on EC2

`small` + int8 runs fine on t3.medium CPU (a 60s reel transcribes in roughly real time). The model (~460MB) downloads on first use into the `whispermodels` volume. If you process many reels, bump to `t3.large` or set `WHISPER_MODEL_SIZE=base`.

## Cost breakdown (us-east-1, on-demand)

| Item | $/month |
|---|---|
| EC2 t3.medium | ~$30 (or ~$18 with savings plan; t3.small ~$15 works if you drop a worker) |
| RDS db.t4g.micro | ~$12 |
| S3 (10GB media) | <$1 |
| Gemini API (~200 items/mo) | $1–3 |
| **Total** | **~$25–45** depending on instance choices |

Going cheaper: a single `t3.small` running everything including Postgres in Docker (skip RDS) lands around $15/month, at the cost of managed backups.
