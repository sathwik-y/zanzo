# Zanzo — Backend Technical Documentation

> **Zanzo (残像)** — "afterimage": the image that lingers after the thing is gone. Zanzo watches your Instagram saves and the reels you DM to a bot account, transcribes them, classifies them, extracts structured data per category, and serves it through a searchable API. This document covers the **backend** end to end. The dashboard is a separate repo: [sathwik-y/zanzo-fe](https://github.com/sathwik-y/zanzo-fe) (see its `TECH-DOC.md`).

---

## 1. Overview

Zanzo is a single-user, self-hosted pipeline. You save reels on Instagram (or DM them to a burner bot account); within minutes Zanzo:

1. **Ingests** them (poller reads the saved collection + DM inbox).
2. **Fetches** the media (video/images/thumbnail) into object storage.
3. **Transcribes** reels (Deepgram multilingual, or local Whisper).
4. **Classifies** each item into one of six categories (Gemini, multimodal).
5. **Extracts** category-specific structured fields (Gemini, strict JSON schema).
6. **Detects CTAs** ("comment X / follow me for the link") and, optionally, **auto-engages**: follows the creator, comments the keyword, watches the bot's DM reply, and harvests the shared link into a **Resources** field.
7. **Embeds** the content for hybrid semantic + text search.
8. Serves everything through a **FastAPI** REST API.

Everything runs locally via `docker compose` for infrastructure plus four Python services. It is designed to lift to AWS with minimal change (S3, RDS, SQS).

---

## 2. Architecture

```
 Instagram ──(instagrapi)──┐
   • saved collection      │
   • DM inbox (xma cards)   ▼
                       ┌─────────┐      ┌──────────────┐
                       │ Poller  │────▶ │ Redis queue  │
                       └─────────┘      └──────┬───────┘
                                               │ item_id
                                               ▼
                                        ┌──────────────┐
                                        │   Worker     │
                                        │  pipeline:   │
                                        │  fetch ─▶ transcribe ─▶ classify ─▶ extract(+cta) ─▶ embed
                                        └──┬────┬────┬────────────┬───────────┬──┘
                       MinIO/S3 ◀─────────┘    │    │            │           │
                                   Deepgram/Whisper │       Gemini (pooled keys)
                                                    ▼            ▼           ▼
                                             ┌──────────────────────────────────┐
                                             │   PostgreSQL 16 + pgvector        │
                                             │   saved_items / extractions /     │
                                             │   media_refs / embeddings /       │
                                             │   engagements / app_state / llm_usage
                                             └──────────────┬────────────────────┘
                                                            ▲
                       ┌─────────────┐   reads/writes       │
                       │ Engagement  │──────────────────────┤
                       │ reconciler  │  (follow/comment/DM, harvest links)
                       └─────────────┘                      │
                                                  ┌─────────┴─────────┐
                                                  │     FastAPI       │
                                                  └─────────┬─────────┘
                                                            ▲
                                                  Next.js dashboard (zanzo-fe)
```

Four long-running services, all from one Python package (`recall`):

| Service | Command | Role |
|---|---|---|
| API | `uvicorn recall.api.main:app` | REST API for the dashboard |
| Worker | `python -m recall.services.worker` | Consumes the queue, runs the pipeline |
| Poller | `python -m recall.services.poller` | Discovers new saved/DMed media, enqueues jobs |
| Engagement | `python -m recall.services.engagement` | Auto-engagement reconciler (follow/comment/harvest) |

> The internal Python package is named `recall` (the project's original placeholder name). Only the product/branding is "Zanzo"; the package name was intentionally left as-is.

---

## 3. Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| API | FastAPI + Uvicorn |
| ORM / migrations | SQLAlchemy 2 + Alembic |
| Database | PostgreSQL 16 + pgvector |
| Queue | Redis 7 (list as queue); interface is swappable to SQS |
| Object storage | S3-compatible — MinIO locally, AWS S3 in prod (boto3) |
| Instagram | instagrapi (unofficial private API) |
| Transcription | Deepgram `nova-2` (primary, multilingual) / faster-whisper (fallback, local) |
| LLM | Google Gemini (`gemini-2.5-flash` + fallbacks) via `google-genai` |
| Embeddings | Gemini `gemini-embedding-001` @ 1536 dims |
| Calendar | `ics` |
| Media fallback download | `yt-dlp` |

---

## 4. Repository layout

```
backend/
  pyproject.toml            # deps, pytest + ruff config
  alembic.ini, alembic/     # migrations (0001 initial, 0002 segments folded in, 0003 v2)
  recall/
    config.py               # pydantic-settings; all env vars
    db.py                   # engine, session factory, Base, get_db dependency
    models.py               # all SQLAlchemy models + enums
    categories.py           # Category enum + per-category extraction JSON schemas
    state.py                # app_state helpers (poller status, engagement config)
    queueing.py             # JobQueue protocol, RedisQueue, InMemoryQueue
    storage.py              # MediaStorage protocol, S3Storage, LocalDirStorage
    instagram/
      client.py             # build_client(): session reuse, sessionid login, challenge handling
      types.py              # DiscoveredMedia dataclass
      saved.py              # fetch_saved() — saved collection
      dms.py                # fetch_dm_shares() — DM inbox xma parsing
    ai/
      gemini.py             # GeminiClient (pooled keys), FakeGemini, build_ai_client()
      prompts.py            # classifier + per-category extractor prompts
      transcription.py      # Transcriber protocol, Deepgram + Whisper, build_transcriber()
    pipeline/
      runner.py             # process_item() — stage orchestration + status machine
      fetch.py              # stage 1: download media -> storage, metadata, hashtags
      transcribe.py         # stage 2: transcription
      visual.py             # needs_video_analysis(), gather_visual_parts(), on-screen detector
      ai_stages.py          # stages 3-5: classify, extract, embed (non-destructive)
      cta.py                # detect_cta(), queue_engagement(), make_cta_stage()
    services/
      poller.py             # poll loop + ingest_discovered()
      worker.py             # queue consumer + build_stages()
      engagement.py         # reconcile_once() + IgEngagementClient + parsers
    api/
      main.py               # create_app(), CORS, router mounting
      deps.py               # require_api_key, get_db, get_storage, get_ai
      schemas.py            # Pydantic response/request models
      search.py             # hybrid_search()
      routes_items.py       # /items*
      routes_admin.py       # /health, /stats, /poller/*, /engagement/*, /resources
      routes_actions.py     # /actions/event/{id}/add-to-calendar
  tests/                    # pytest; runs against a separate <db>_test database
  fixtures/                 # recorded payloads (DM inbox, generic_xma, etc.)
scripts/                    # ops + spikes (poll_once, requeue_all, reprocess_all, run_engagement, ...)
docker-compose.yml          # postgres, redis, minio, + app profile (api/worker/poller/engagement)
Dockerfile.backend
docs/aws-deploy.md          # AWS deployment guide
```

---

## 5. Configuration

All settings live in `recall/config.py` (pydantic-settings), read from the repo-root `.env`. Defaults match `docker-compose.yml`.

| Env var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://recall:recall@localhost:5433/recall` | Postgres DSN |
| `REDIS_URL` | `redis://localhost:6380/0` | Redis for the job queue |
| `QUEUE_NAME` | `recall:jobs` | Redis list key |
| `S3_ENDPOINT_URL` | `http://localhost:9000` | S3/MinIO endpoint (empty = real AWS S3) |
| `S3_PUBLIC_ENDPOINT_URL` | `""` | Browser-reachable endpoint for presigned URLs |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | `recall` / `recall-secret` | Storage creds |
| `S3_BUCKET` | `recall-media` | Media bucket |
| `S3_REGION` | `us-east-1` | Region for signing |
| `IG_USERNAME` / `IG_PASSWORD` | `""` | Burner login (fallback) |
| `IG_SESSIONID` | `""` | **Preferred** login: sessionid cookie (skips checkpoints) |
| `INSTAGRAPI_SESSION_PATH` | `data/ig.session.json` | Persisted device/session settings |
| `POLL_INTERVAL_SECONDS` | `300` | Poll cadence |
| `POLL_JITTER_SECONDS` | `30` | ± jitter to look human |
| `MAX_ITEMS_PER_POLL` | `50` | Safety cap per poll |
| `GEMINI_API_KEY` | `""` | Primary Gemini key |
| `GEMINI_API_KEYS` | `""` | Comma-separated key pool; round-robin + 429 fallthrough |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Primary generation model |
| `GEMINI_FALLBACK_MODELS` | `gemini-2.5-flash-lite,gemini-2.0-flash` | Fallbacks on 429/5xx |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector size (matches pgvector column) |
| `GEMINI_INPUT_PRICE_PER_MTOK` / `..._OUTPUT_...` | `0.30` / `2.50` | For the cost dashboard |
| `DEEPGRAM_API_KEY` | `""` | If set, Deepgram is the transcriber; else Whisper |
| `DEEPGRAM_MODEL` | `nova-2` | Has dedicated Telugu/Hindi/English support |
| `WHISPER_MODEL_SIZE` / `WHISPER_COMPUTE_TYPE` | `small` / `int8` | Local fallback transcriber |
| `VISUAL_EXTRACTION` | `true` | Send video/images to Gemini for silent reels & posts |
| `TRANSCRIPT_WEAK_CHARS` | `15` | Below this transcript length, a reel is treated as silent |
| `API_KEY` | `change-me` | Shared secret; required in `X-API-Key` on all routes but `/health` |
| `RECALL_FAKE_INSTAGRAM` / `RECALL_FAKE_GEMINI` | `false` | Fixture mode: run the pipeline with zero external calls |

---

## 6. Data model

PostgreSQL. Models in `recall/models.py`; schema via Alembic.

### `saved_items` — one row per ingested reel/post
| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `media_pk` | text UNIQUE | Instagram's internal ID; primary dedup key |
| `media_type` | str | `POST` / `REEL` / `CAROUSEL` / `IGTV` |
| `source` | str | `SAVED` (saved collection) or `DM` (shared to the bot) |
| `instagram_url`, `author_username`, `author_full_name`, `caption` | text | metadata |
| `hashtags` | text[] | parsed from caption |
| `post_created_at`, `saved_at`, `ingested_at` | timestamptz | |
| `category` | str | one of the six categories, or null |
| `category_confidence` | float | classifier confidence (1.0 if user-set) |
| `transcript` | text | null for non-video |
| `transcript_segments` | jsonb | `[{start, end, text}]` for click-to-seek |
| `transcript_lang` | str | detected language |
| `transcript_provider` | str | `deepgram` or `whisper` |
| `resources` | jsonb | `[{url, text, source, received_at}]` harvested by engagement |
| `status` | str | item status machine (below) |
| `error_log` | jsonb | `{stage, error, traceback_tail, at}` on failure |
| `archived` | bool | hidden from default views |

Relationships: `extraction` (1:1), `media_refs` (1:many), `embedding` (1:1). All cascade-delete.

### `extractions`
`id, item_id (unique FK), schema_version, payload (jsonb), created_at`. `payload` conforms to the per-category schema in `categories.py`.

### `media_refs`
`id, item_id FK, s3_key, media_kind (VIDEO|IMAGE|THUMBNAIL|AUDIO_EXTRACT), bytes`.

### `embeddings`
`item_id (PK/FK), vector vector(1536), model`. ivfflat cosine index `ix_embeddings_vector_cosine`.

### `engagements` — one per CTA interaction
`id, item_id (unique FK), creator_username, creator_user_id, media_pk, keyword, needs_follow, channel (comment|dm|both), status (engagement machine), attempts, commented_at, dm_sent_at, resource_received_at, last_error, created_at, updated_at`.

### `app_state` — key/value jsonb
`poller` → `{status, last_run_at, last_new_items, last_error}`; `engagement` → caps config (see §11).

### `llm_usage` — per-call token accounting for the cost dashboard
`id, item_id, stage (classify|extract|cta|embed), model, input_tokens, output_tokens, cost_usd, created_at`.

### Item status machine
`PENDING → FETCHING → TRANSCRIBING → CLASSIFYING → EXTRACTING → EMBEDDING → COMPLETED`.
On a stage error: `FAILED_FETCH | FAILED_TRANSCRIBE | FAILED_CLASSIFY | FAILED_EXTRACT | FAILED_EMBED`, with `error_log` populated. Stages are **idempotent** and **non-destructive**: re-running skips already-done work, and an AI stage that fails while prior output exists keeps that output instead of regressing.

### Six categories (`categories.py`)
`EDUCATIONAL, EVENT, RECIPE, TRAVEL, TECH_REFERENCE, OTHER`. Each has a strict JSON schema used both as the Gemini `response_schema` and the contract for `extractions.payload`. Examples: EVENT → `{title, event_type, starts_at, ends_at, venue_name, city, rsvp_url, ticket_url, ...}`; RECIPE → `{dish_name, ingredients[], steps[], dietary_tags[], ...}`; TECH_REFERENCE → `{subject, tools_mentioned[], code_or_command_snippets[], key_insights[], ...}`.

---

## 7. Ingestion (poller)

`recall/instagram/client.py` builds the instagrapi client. Login order: reuse persisted session file → `login_by_sessionid(IG_SESSIONID)` → username/password. The session file is always re-dumped so device identifiers stay stable (Instagram flags changing devices). `ChallengeRequired`/`LoginRequired` raise `InstagramChallengeError`.

Two ingestion paths (`recall/instagram/`):

- **Saved collection** (`saved.py`): `cl.collection_medias("ALL_MEDIA_AUTO_COLLECTION", amount=N)`.
- **DM shares** (`dms.py`): reels DMed to the bot arrive as `xma_clip` / `xma_media_share` items in the pending + normal inboxes. The reel permalink is `item["xma_clip"][0]["target_url"]`; the numeric `media_pk` is the first segment of the `id` query param. Pending threads are auto-approved so future shares land in the normal inbox.

Both produce `DiscoveredMedia` dataclasses. `services/poller.py`:
- `poll_once()` gathers saved + DM media, `ingest_discovered()` dedups (within batch and against `saved_items.media_pk`), inserts `PENDING` rows, and enqueues each `item_id`.
- `run_forever()` loops with `POLL_INTERVAL_SECONDS` ± jitter. On `InstagramChallengeError` it sets `app_state.poller.status = challenge_required` and pauses until the dashboard hits `/poller/resume`.

---

## 8. Queue & storage

- **Queue** (`queueing.py`): `JobQueue` protocol (`enqueue`, `dequeue`, `depth`). `RedisQueue` uses `LPUSH`/`BRPOP`; dequeue tolerates transient socket timeouts. `InMemoryQueue` for tests. Swapping to SQS = one class implementing the protocol.
- **Storage** (`storage.py`): `MediaStorage` protocol. `S3Storage` (boto3) works against MinIO or AWS S3; presigned URLs are signed against `S3_PUBLIC_ENDPOINT_URL` so they're browser-reachable. `LocalDirStorage` for tests.

---

## 9. Pipeline

`recall/pipeline/runner.py::process_item(db, item_id, stages)` walks the stage list, sets the running status before each stage, captures failures into `FAILED_<STAGE>` + `error_log`, and sets `COMPLETED` at the end. Stages are built in `services/worker.py::build_stages()`.

| Stage | Module | What it does |
|---|---|---|
| `fetch` | `fetch.py` | `media_info()` for metadata; downloads video/images/thumbnail (yt-dlp fallback for video); uploads to storage; writes `media_refs`; parses hashtags. Idempotent (skips kinds already present). |
| `transcribe` | `transcribe.py` | Pulls video from storage, runs the configured transcriber, stores transcript + segments + lang + provider. Skips non-video. |
| `classify` | `ai_stages.py` | Gathers visual parts, calls Gemini classifier → category + confidence. Non-destructive on failure. |
| `extract` (+ `cta`) | `ai_stages.py`, `cta.py` | Category-specific extraction → `extractions.payload`; then CTA detection (non-fatal) queues an `Engagement` if a CTA is found. |
| `embed` | `ai_stages.py` | Builds embed text (caption + transcript + key fields), stores the pgvector row. |

### Transcription (`ai/transcription.py`)
`build_transcriber()` returns `DeepgramTranscriber` if `DEEPGRAM_API_KEY` is set, else `WhisperTranscriber`. Both return `TranscriptResult(text, segments, lang, provider)`. Deepgram uses `nova-2` with `detect_language` (English/Hindi/Telugu and more); Whisper is local, zero-cost, multilingual.

### Visual extraction (`pipeline/visual.py`)
`gather_visual_parts()` always includes images (post photos / reel thumbnail). It additionally sends the **video** to Gemini when `needs_video_analysis()` is true: the transcript is shorter than `TRANSCRIPT_WEAK_CHARS`, **or** it references on-screen content (`references_on_screen()` matches phrases like "link in bio", "as you can see on the screen", "shared below"). Keeps cost down — most reels stay text-only.

---

## 10. AI layer (`ai/gemini.py`)

`GeminiClient` holds a **pool of clients**, one per key from `GEMINI_API_KEY` + `GEMINI_API_KEYS` (deduped). Per request it round-robins to the next key (`_client_order()` advances a cursor), and falls through on `429` (quota) and `5xx` (capacity) — first across models (`GEMINI_MODEL` → fallbacks), then across keys. This multiplies the free-tier daily quota (each key/model has its own).

Methods: `classify()`, `extract()`, `detect_cta()`, `embed()` — each records a `llm_usage` row with token counts and computed cost. Multimodal: images go inline as `Part.from_bytes`; videos upload via the Files API on the **same** client that runs generation (file refs are project-bound), then get deleted. `FakeGemini` (keyword heuristics + deterministic embeddings) backs `RECALL_FAKE_GEMINI` mode and the test suite. Prompts live in `ai/prompts.py`; all generation is temperature 0 with `response_mime_type=application/json` + `response_schema`.

---

## 11. Auto-engagement (`services/engagement.py`)

When a reel's caption/transcript says "comment KEYWORD (and follow me) to get the link", `cta.py::detect_cta()` (a small structured Gemini call) returns `{is_cta, keyword, needs_follow, channel}`, and `queue_engagement()` inserts an `Engagement(PENDING)` for items with a known creator.

`reconcile_once(db, client, config, now)` is a pure, testable function (sleeper injectable) that advances each engagement one step:

```
PENDING ──(follow if needed, within cap)──▶ FOLLOWING ──(comment keyword, within cap)──▶ AWAITING_REPLY
AWAITING_REPLY ──(creator DM has a link)──▶ RESOURCE_RECEIVED      (link appended to item.resources)
               ──(reply is a tap-gated card)──▶ INTERACTION_REQUIRED (claim link saved)
               ──(no reply after dm_fallback_after_s, channel dm/both)──▶ DM_SENT ──▶ (back to watching)
               ──(no reply after exhaust_after_s)──▶ EXHAUSTED
any write error ──(attempts++ ; ≥ MAX_ATTEMPTS)──▶ FAILED
```

- **Caps & safety**: config in `app_state.engagement` (editable via the API/dashboard), defaults: `enabled=true`, `daily_follow_cap=daily_comment_cap=daily_dm_cap=8`, `min_delay_s=120`, `max_delay_s=600`, `dm_fallback_after_s=7200` (2h), `exhaust_after_s=172800` (2d). Every write (follow/comment/DM) sleeps a random delay. Counts come from row timestamps, so over-cap engagements are simply retried when the 24h window rolls forward.
- **Reply harvesting**: `creator_messages()` reads the raw `direct_v2/threads/{id}/` items; `parse_thread_item()` extracts links from plain text, `link` attachments, `xma_clip`/`xma_media_share`, and rich `generic_xma` cards (including `cta_buttons[].action_url`). ManyChat-style opening messages with only a **postback** button (link gated behind an in-app tap) are flagged `needs_interaction` → the engagement becomes `INTERACTION_REQUIRED` and a claim deep-link is saved. instagrapi's naive timestamps are coerced to UTC before comparison.

> **TOS note:** follows/comments/DMs are writes — far higher ban-risk than read-only ingestion. Use a burner only; the feature is cap-limited and disableable from the dashboard.

---

## 12. Search (`api/search.py`)

`hybrid_search()` combines a **semantic** leg (embed the query with Gemini, rank by `vector <=> query` cosine distance over `embeddings`) and a **text** leg (`ILIKE` over caption, transcript, and the extraction payload cast to text). Results are merged; an item matched by both ranks highest; each result carries a `match_reason` (`semantic`, `text`, or `semantic + text`).

---

## 13. REST API reference

Base URL: `http://localhost:8000`. **Auth:** every endpoint except `GET /health` requires header `X-API-Key: <API_KEY>`. JSON in/out. Interactive docs at `/docs`.

### Items

#### `GET /items`
List items, newest first (or ranked if searching).
Query params: `category` (e.g. `RECIPE`), `status` (`COMPLETED`, `failed`, or a specific status), `source` (`SAVED`/`DM`), `archived` (bool, default false), `date_from`, `date_to` (ISO datetime, on `saved_at`), `search` (string → hybrid search), `limit` (≤100, default 20), `offset`.
Response: `{ items: ItemSummary[], total, limit, offset }`.
`ItemSummary`: `id, media_pk, media_type, source, instagram_url, author_username, author_full_name, caption, category, category_confidence, status, archived, saved_at, ingested_at, thumbnail_url, extraction (payload | null), match_reason`.

#### `GET /items/{id}`
Full detail. Response `ItemDetail` = `ItemSummary` + `hashtags, post_created_at, transcript, transcript_segments, transcript_lang, transcript_provider, resources, error_log, media: [{kind, url (presigned), bytes}], engagement: {status, keyword, needs_follow, channel, creator_username, commented_at, dm_sent_at, last_error} | null`.

#### `GET /items/{id}/media`
Presigned URLs for all media refs: `[{kind, url, bytes}]`.

#### `POST /items/{id}/recategorize`  body `{ "category": "RECIPE" }`
Manual override; sets confidence 1.0 and re-runs extraction + embedding inline. Returns `ItemDetail`.

#### `POST /items/{id}/retry`  → 202
Resets the item to `PENDING` and re-enqueues it.

#### `PATCH /items/{id}`  body `{ "archived": true }`
Archive/unarchive. Returns `ItemSummary`.

#### `DELETE /items/{id}`  → 204
Removes from the index. Does **not** unsave on Instagram.

### Actions

#### `POST /actions/event/{id}/add-to-calendar`
For `EVENT` items with a `starts_at`. Returns an `.ics` file (`text/calendar`). 422 if not an extracted event or no start datetime.

### Admin

#### `GET /health` → `{ "status": "ok" }`  *(no auth)*

#### `GET /stats`
`{ total_items, by_category: {CAT: n}, by_status: {STATUS: n}, failed_count, llm_cost_total_usd, llm_cost_month_usd, items_last_7_days }`.

#### `GET /poller/status`
`{ status, last_run_at, last_new_items, last_error, queue_depth }`.

#### `POST /poller/resume`
Clears a challenge state and sets the poller back to `running`. Returns poller status.

#### `GET /engagement/config` / `PUT /engagement/config`
Get/set the engagement caps (`EngagementConfig`: `enabled, daily_follow_cap, daily_comment_cap, daily_dm_cap, min_delay_s, max_delay_s, dm_fallback_after_s, exhaust_after_s`).

#### `GET /engagement?limit=50`
Recent engagement rows: `[{id, item_id, creator_username, keyword, needs_follow, channel, status, attempts, last_error, commented_at, resource_received_at, created_at}]`.

#### `GET /resources`
Drives the dashboard Resources view: every engagement with its item's harvested links — `[{item_id, headline, creator_username, keyword, status, needs_follow, resources: [{url, text, source, received_at}], last_error}]`.

---

## 14. Running it

```bash
cp .env.example .env            # fill IG sessionid, Gemini key(s), Deepgram key, API_KEY
docker compose up -d postgres redis minio
python -m venv .venv && .venv/Scripts/activate   # bin/activate on unix
pip install -e "backend[dev]"
cd backend && alembic upgrade head && cd ..

# four services (separate terminals) — or: docker compose --profile app up --build
uvicorn recall.api.main:app --port 8000
python -m recall.services.worker
python -m recall.services.poller
python -m recall.services.engagement
```

Dashboard: separate repo [zanzo-fe](https://github.com/sathwik-y/zanzo-fe), pointed at `BACKEND_URL=http://localhost:8000`.

### Ops scripts (`scripts/`)
- `poll_once.py` — one poll cycle (cron-friendly).
- `requeue_all.py [--all]` — reset non-completed (or all) items to `PENDING` and re-enqueue.
- `reprocess_all.py` — reprocess every item synchronously through the pipeline (bypasses the flaky-on-Windows Redis queue).
- `run_engagement.py` — run the reconciler for a few passes against live Instagram.
- `debug_state.py` — print status/category/extraction/engagement for every item.
- `spike_*.py` — exploration scripts (Gemini, instagrapi, Deepgram, DM payloads).

---

## 15. Testing

`cd backend && python -m pytest` (67 tests) and `python -m ruff check .`.

- **DB isolation:** the suite creates and uses a **separate** `<db>_test` database (`tests/conftest.py`), truncating between tests. This is deliberate — `reconcile_once()` scans the whole `engagements` table, so sharing the dev DB would let tests mutate real rows. Never point tests at the dev DB.
- **Fixture mode:** `RECALL_FAKE_INSTAGRAM=true` + `RECALL_FAKE_GEMINI=true` runs the entire pipeline with zero external calls.
- Coverage spans models, queue/storage, DM parsing, poller diff, pipeline orchestration + failure/retry, transcription mapping, visual triggers, classify/extract for all categories, CTA detection, the engagement state machine (caps, DM fallback, generic_xma parsing, naive-timestamp handling), API auth + every endpoint, hybrid search, and .ics generation.

---

## 16. Deployment

See [`docs/aws-deploy.md`](aws-deploy.md): RDS (Postgres+pgvector), S3 (drop `S3_ENDPOINT_URL`), ElastiCache or SQS for the queue, EC2/ECS for the services. Recommended hybrid: run the poller from a residential IP (Instagram flags datacenter IPs) while the API/worker live on AWS. Expected cost at personal volume: ~$20–45/month.
