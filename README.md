# Recall

Your Instagram saves, organized and searchable. Save a reel on Instagram (or DM it to your bot account) and within minutes it shows up in your dashboard — transcribed, categorized, and with the useful parts extracted into structured data: event dates, recipe ingredients, travel spots, code snippets.

Stop losing recipes, events and recommendations in your saved folder.

## What it does

1. **Automatic ingestion, two ways.** A poller watches your Instagram saved collection via [instagrapi](https://github.com/subzeroid/instagrapi). You can also DM any reel to the bot account and it gets picked up the same way — no URL pasting, ever.
2. **Category-aware AI extraction.** Every item is transcribed locally with Whisper, then classified (Educational / Event / Recipe / Travel / Tech / Other) and run through a category-specific extractor. An event reel yields `starts_at`, `venue_name`, `ticket_url`; a recipe reel yields ingredients with quantities and ordered steps; a tech reel yields the actual commands shown. Not just tags — structured fields you can act on ("Add to calendar" generates an .ics from the extraction).
3. **Self-hosted, your data.** Runs on your laptop or your AWS account. Postgres + pgvector for hybrid semantic search ("that tokyo ramen place" finds the reel even if the caption never says "ramen"). No subscription, no third-party cloud holding your saves.

## How it compares

Tools like ReelRecall, Dewey and Bookmarkjar already organize Instagram saves, and if you want a polished hosted product you should use one of them. Recall exists because they all share three gaps: you have to manually send each post to them, their extraction is generic (summary + tags) rather than schema-per-category, and your data lives in their cloud behind a subscription. Recall trades their polish for automation, structured extraction and ownership.

## Architecture

```
 Instagram ──(instagrapi: saved collection + DMs)──▶ Poller ──▶ Redis queue
                                                                    │
                                                                    ▼
                                                                  Worker
                                          fetch ▶ transcribe ▶ classify ▶ extract ▶ embed
                                            │       (Whisper,    └──(Gemini, per-category JSON schemas)
                                            ▼        local)                │
                                          MinIO/S3                         ▼
                                                                 Postgres + pgvector
                                                                    ▲
                                                  FastAPI ──────────┘
                                                     ▲
                                              Next.js dashboard
```

- **Backend:** Python / FastAPI, SQLAlchemy, Alembic
- **Pipeline:** faster-whisper (local transcription), Gemini (classification + structured extraction + embeddings), with automatic model fallback when the primary model is at capacity
- **Storage:** Postgres 16 + pgvector (hybrid semantic + text search), MinIO or S3 for media
- **Frontend:** Next.js 16, Tailwind, dark-mode dashboard with per-category views
- **Queue:** Redis locally; the queue interface is small so an SQS swap on AWS is one class

## ⚠️ Read this before you set it up

**Automating an Instagram account violates Instagram's Terms of Service and can get the account banned.** This is not a hypothetical; Instagram actively detects automation.

- **Use a dedicated burner account, not your main.** Save reels to it directly, or DM reels to it from your main account (this is what the DM ingestion path is for — your main account never does anything automated).
- Polling is conservative by default (5-minute interval with jitter, one persistent session, human-like request pacing), but the risk is never zero.
- Run the poller from a residential IP (your home machine) when possible. Datacenter IPs get flagged faster.
- When Instagram throws a verification challenge, the poller pauses and the dashboard shows a "needs attention" banner: approve the login in the Instagram app, click resume.

This is a personal tool. You bring your own account, your own API keys, your own infrastructure, and your own risk.

## Setup

Prerequisites: Docker, Python 3.12+, Node 22+ (Node only if you run the dashboard outside Docker), a [Gemini API key](https://aistudio.google.com/apikey), and a (burner) Instagram account.

```bash
git clone <this repo> && cd recall
cp .env.example .env       # fill in IG credentials, Gemini key, API key
docker compose up -d postgres redis minio

# backend
python -m venv .venv && .venv/Scripts/activate    # or bin/activate on unix
pip install -e "backend[dev]"
cd backend && alembic upgrade head && cd ..

# run the three services (separate terminals, or use docker compose --profile app up)
uvicorn recall.api.main:app --port 8000
python -m recall.services.worker
python -m recall.services.poller

# dashboard
cd frontend && npm install && npm run dev          # http://localhost:3000
```

**Instagram login tip:** password login from a new device usually triggers a checkpoint. The reliable path is the `IG_SESSIONID` cookie: log into instagram.com in your browser as the bot account, open DevTools → Application → Cookies → copy `sessionid` into `.env`. The session persists to `data/ig.session.json` after that.

Everything (API, worker, poller, dashboard) can also run fully in Docker: `docker compose --profile app up --build`.

### Try it without any credentials

Set `RECALL_FAKE_INSTAGRAM=true` and `RECALL_FAKE_GEMINI=true` in `.env` to run the entire pipeline against fixtures — useful for development and for kicking the tires before you commit a burner account.

## Extending

- **Add a category:** add the enum value and JSON schema in `backend/recall/categories.py`, an extractor instruction in `backend/recall/ai/prompts.py`, and (optionally) a renderer in `frontend/components/extraction-view.tsx`. That's it — classification, extraction, storage and search pick it up automatically.
- **Swap the LLM:** implement the three-method interface in `backend/recall/ai/gemini.py` (`classify`, `extract`, `embed`). The pipeline only knows that interface.
- **Swap the queue for SQS:** implement `JobQueue` (two methods) in `backend/recall/queueing.py`.
- **Deploy to AWS:** see [docs/aws-deploy.md](docs/aws-deploy.md).

## Development

```bash
cd backend
python -m pytest        # 34 tests; DB tests need the docker services up
python -m ruff check .
```

## License

MIT. This is a personal project, not a service — PRs welcome, but there is no SLA and no support.
