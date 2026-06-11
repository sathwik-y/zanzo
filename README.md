# Zanzo 

Your Instagram saves, organized and searchable. Save a reel on Instagram (or DM it to your bot account) and within minutes it shows up in your dashboard — transcribed, categorized, and with the useful parts extracted into structured data: event dates, recipe ingredients, travel spots, code snippets.

The reel scrolls past; the afterimage stays. Stop losing recipes, events and recommendations in your saved folder.

## What it does

1. **Automatic ingestion, two ways.** A poller watches your Instagram saved collection via [instagrapi](https://github.com/subzeroid/instagrapi). You can also DM any reel to the bot account and it gets picked up the same way — no URL pasting, ever.
2. **Category-aware AI extraction.** Every item is transcribed, then classified (Educational / Event / Recipe / Travel / Tech / Other) and run through a category-specific extractor. An event reel yields `starts_at`, `venue_name`, `ticket_url`; a recipe reel yields ingredients with quantities and ordered steps; a tech reel yields the actual commands shown. Not just tags — structured fields you can act on ("Add to calendar" generates an .ics from the extraction).
3. **Self-hosted, your data.** Runs on your laptop or your AWS account. Postgres + pgvector for hybrid semantic search ("that tokyo ramen place" finds the reel even if the caption never says "ramen"). No subscription, no third-party cloud holding your saves.
4. **Multi-user.** Full login/signup with JWT auth. Each user links their Instagram account (verified by DMing a one-time code to the bot), and from then on every reel they DM lands in *their* library only. Admins get an instance-wide panel: users, global stats, poller health, engagement caps.

### Beyond the basics

- **Multilingual transcription.** Uses Deepgram (nova-2) when a key is set, covering English, Hindi, Telugu and more with per-reel language detection. Falls back to local Whisper (zero cost, fully self-hosted) when no key is configured.
- **Visual extraction for silent reels.** Reels with no useful audio — or that point at on-screen content ("link in bio", "as you can see on the screen") — and image posts are analyzed visually by Gemini, so the caption and frames are read, not just the audio.
- **Automated resource fetching.** When a reel says "comment GUIDE and follow me to get the link", the bot account can follow the creator, comment the keyword, and watch its DMs for the reply — harvesting the shared link into a **Resources** field on the item. This is opt-in-by-default with daily caps and randomized delays you control from the dashboard. See the warning below; this is the highest-risk feature.

## How it compares

Tools like ReelRecall, Dewey and Bookmarkjar already organize Instagram saves, and if you want a polished hosted product you should use one of them. Zanzo exists because they all share three gaps: you have to manually send each post to them, their extraction is generic (summary + tags) rather than schema-per-category, and your data lives in their cloud behind a subscription. Zanzo trades their polish for automation, structured extraction and ownership.

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
- **Frontend:** Next.js 16, Tailwind, dark-mode dashboard with per-category views — lives in a **separate repo**: [sathwik-y/zanzo-fe](https://github.com/sathwik-y/zanzo-fe)
- **Queue:** Redis locally; the queue interface is small so an SQS swap on AWS is one class

## ⚠️ Read this before you set it up

**Automating an Instagram account violates Instagram's Terms of Service and can get the account banned.** This is not a hypothetical; Instagram actively detects automation.

- **Use a dedicated burner account, not your main.** Save reels to it directly, or DM reels to it from your main account (this is what the DM ingestion path is for — your main account never does anything automated).
- Polling is conservative by default (5-minute interval with jitter, one persistent session, human-like request pacing), but the risk is never zero.
- Run the poller from a residential IP (your home machine) when possible. Datacenter IPs get flagged faster.
- When Instagram throws a verification challenge, the poller pauses and the dashboard shows a "needs attention" banner: approve the login in the Instagram app, click resume.
- **Auto-engagement writes to Instagram (follows, comments, DMs).** These are far higher ban-risk than the read-only ingestion. It runs under daily caps with randomized delays and is fully controllable (and disableable) from the Settings page. Only ever point it at a burner account.

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

# run the services (separate terminals, or use docker compose --profile app up)
uvicorn recall.api.main:app --port 8000
python -m recall.services.worker
python -m recall.services.poller
python -m recall.services.engagement   # auto-engagement reconciler (optional)
```

The dashboard is a separate project — clone [sathwik-y/zanzo-fe](https://github.com/sathwik-y/zanzo-fe),
point it at this backend (`BACKEND_URL=http://localhost:8000`), and `npm run dev`.

**Instagram login tip:** password login from a new device usually triggers a checkpoint. The reliable path is the `IG_SESSIONID` cookie: log into instagram.com in your browser as the bot account, open DevTools → Application → Cookies → copy `sessionid` into `.env`. The session persists to `data/ig.session.json` after that.

Everything (API, worker, poller, dashboard) can also run fully in Docker: `docker compose --profile app up --build`.

### Accounts, roles and Instagram linking

- Sign up on the dashboard. The **first account** on an instance becomes admin automatically; emails in `ADMIN_EMAILS` are promoted too. Set `ALLOW_SIGNUP=false` to lock a personal instance afterwards.
- To receive reels by DM, link your Instagram in **Settings**: enter your handle, get a code, DM `ZANZO <code>` to the bot account from your IG account. The poller binds your Instagram's stable numeric id — renaming your IG handle later won't break the mapping.
- Items from the bot's own saved collection (and DMs from unlinked senders) are visible to admins only.
- The `API_KEY` header (`X-API-Key`) still works as an unscoped *service* credential for scripts and ops.

### Try it without any credentials

Set `RECALL_FAKE_INSTAGRAM=true` and `RECALL_FAKE_GEMINI=true` in `.env` to run the entire pipeline against fixtures — useful for development and for kicking the tires before you commit a burner account.

## Extending

- **Add a category:** add the enum value and JSON schema in `backend/recall/categories.py`, an extractor instruction in `backend/recall/ai/prompts.py`, and (optionally) a renderer in `components/extraction-view.tsx` over in the [frontend repo](https://github.com/sathwik-y/zanzo-fe). That's it — classification, extraction, storage and search pick it up automatically.
- **Swap the LLM:** implement the three-method interface in `backend/recall/ai/gemini.py` (`classify`, `extract`, `embed`). The pipeline only knows that interface.
- **Swap the queue for SQS:** implement `JobQueue` (two methods) in `backend/recall/queueing.py`.
- **Deploy to AWS:** see [docs/aws-deploy.md](docs/aws-deploy.md).

## Development

```bash
cd backend
python -m pytest        # 34 tests; DB tests need the docker services up
python -m ruff check .
```

## A personal project

This is a personal project, not a service — PRs welcome, but there is no SLA and no support.
