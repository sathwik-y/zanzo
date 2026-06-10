# Instagram Saved-Reels Organizer with AI Extraction

> **Working name:** TBD (placeholder: `Recall`)
> **Status:** Spec, pre-build
> **Builder:** Sathwik Yellapragada
> **Scope:** Personal-use, open-source, AWS-hosted backend, web dashboard
> **Architectural style of this doc:** Detailed but architectural. Components, flows, data shapes, dependencies, rationale. Class-level structure deferred to Claude Code.

---

## 1. What this is

A system that watches your Instagram Saved collection, automatically pulls every new saved item (post, reel, carousel) as it's added, runs it through an AI extraction pipeline tailored to *what type of content it is*, stores everything in a structured, queryable index, and surfaces it through a web dashboard where you can search, filter, browse by category, and act on structured extractions (e.g., "Add this event to my calendar").

Goal: never lose another saved reel. Never have to remember which save had that recipe / event date / travel tip. Searchable, organized, automatic.

## 2. What this is NOT

- Not a commercial SaaS. Not setting up Instagram credentials for anyone else. Open-source; users bring their own creds.
- Not competing with ReelRecall, Dewey, or Bookmarkjar. They exist; this is yours, with the features you specifically want that they don't have.
- Not trying to be cloud-multi-tenant. Single-user per deployment.
- Not aiming for mass distribution. README will explicitly say "this is a personal tool; you self-host it."
- Not handling content moderation, copyright, or republishing. Read + organize for personal recall only.

## 3. The three things this has that ReelRecall doesn't

This is the actual wedge. Worth keeping it short and clear because everything else flows from these:

1. **Automatic pulling from your Saved collection** via `instagrapi` polling. You save on Instagram normally; the system picks it up within minutes. No manual URL pasting.
2. **Category-specific structured extraction.** Not just transcripts and tags — actual structured fields per content type (event date + venue + RSVP link, recipe ingredients + steps, travel location + restaurants mentioned, etc.). Different schema per category.
3. **Open source, self-hosted, your own data.** Runs on your AWS or your laptop. No subscription, no data going to a third party's cloud.

Everything in this spec exists to deliver those three things well.

---

## 4. High-level architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       AWS deployment                            │
│                                                                 │
│  ┌──────────────────┐   ┌──────────────────┐   ┌─────────────┐ │
│  │  Poller Service  │──▶│  Ingestion Queue │──▶│  Worker     │ │
│  │  (instagrapi)    │   │  (SQS or Redis)  │   │  Pool       │ │
│  └──────────────────┘   └──────────────────┘   └─────────────┘ │
│         │                                              │        │
│         │                                              ▼        │
│         │                                       ┌─────────────┐ │
│         │                                       │ Media Fetch │ │
│         │                                       │ (yt-dlp +   │ │
│         │                                       │  instagrapi)│ │
│         │                                       └─────────────┘ │
│         │                                              │        │
│         ▼                                              ▼        │
│  ┌──────────────────┐                          ┌─────────────┐ │
│  │   PostgreSQL     │◀─────────────────────────│ Transcribe  │ │
│  │   + pgvector     │                          │ (Whisper)   │ │
│  │                  │                          └─────────────┘ │
│  │  - saved_items   │                                 │        │
│  │  - extractions   │                                 ▼        │
│  │  - media_refs    │                          ┌─────────────┐ │
│  │  - embeddings    │◀─────────────────────────│ Classify +  │ │
│  └──────────────────┘                          │ Extract     │ │
│         ▲                                       │ (Claude API)│ │
│         │                                       └─────────────┘ │
│         │                                              │        │
│         │                                              ▼        │
│         │                                       ┌─────────────┐ │
│         │                                       │   S3 Media  │ │
│         │                                       │   Storage   │ │
│         │                                       └─────────────┘ │
│         │                                                       │
│  ┌──────┴───────────┐                                          │
│  │   FastAPI        │                                          │
│  │   Backend API    │                                          │
│  └──────┬───────────┘                                          │
└─────────┼───────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────┐
│  Next.js Web     │
│  Dashboard       │
│  (Vercel or      │
│   self-hosted)   │
└──────────────────┘
```

`ASSUMPTION:` Python backend (FastAPI), Next.js dashboard, Postgres + pgvector. Reasoning: `instagrapi` is Python; FastAPI is your stack; Next.js gives clean dashboard UX with low setup; pgvector avoids running a separate vector DB. Flag if you want Spring Boot for the API layer — viable but you'd need a Python-only ingestion microservice anyway since `instagrapi` is Python.

`ASSUMPTION:` LLM = Claude API (Anthropic). You already have Anthropic access via Claude Code; Claude is strong at structured JSON extraction; consistent with the rest of your portfolio.

## 5. Component breakdown

### 5.1 Poller Service

**Responsibility:** Continuously polls your Instagram Saved collection via `instagrapi`. Diffs against what's already in the database. Enqueues new items for processing.

**Mechanics:**
- Runs on a fixed schedule (configurable; default 5-minute interval).
- Logs in once at startup using stored session credentials. Session file persisted to disk to avoid repeated logins (Instagram flags repeated logins as suspicious).
- Calls `instagrapi`'s `account_saved_medias()` or the Collections API to pull current Saved list.
- For each item: check if its `media_pk` exists in `saved_items`. If not, insert a new row with status `PENDING` and enqueue a job.
- Handles Instagram's challenges/checkpoints gracefully: on `ChallengeRequired`, the service pauses, logs the issue, and surfaces it to the dashboard's "needs attention" panel. You manually resolve in the Instagram app on your phone, then click "resume" in the dashboard.

**Config:**
- `IG_USERNAME`, `IG_PASSWORD` (env, NEVER committed)
- `POLL_INTERVAL_SECONDS` (default 300)
- `INSTAGRAPI_SESSION_PATH` (default `/data/session.json`)
- `MAX_ITEMS_PER_POLL` (safety cap; default 50)

**Anti-ban notes (this is the real risk and we plan for it):**
- Use a session file. Do not log in repeatedly.
- Random jitter on polling interval (±30s).
- Use a residential-IP if you're polling from AWS — Instagram aggressively flags datacenter IPs. **`ASSUMPTION`: you'll either (a) run the poller from your home network and only put the API/dashboard on AWS, OR (b) accept higher ban risk on the burner account.** Flag which.
- Recommendation: **create a burner Instagram account dedicated to this**, follow yourself from it, and use the burner account's session — not your main. Saved items are per-account, so you'd need to re-save to the burner. Annoying but ban-safe. OR accept the risk on your main and configure conservative polling.

### 5.2 Ingestion Queue

**Responsibility:** Decouples poller from workers; smooths spikes when many items get saved at once.

**Choice:**
- **Simple path:** Redis with a list-as-queue (`LPUSH` / `BRPOP`). Cheap, runs on the same EC2 box.
- **Robust path:** AWS SQS. Built for this. Costs near-zero at personal scale.

`ASSUMPTION:` SQS, since you already know AWS and it's effectively free at this volume. Override to Redis if you want fewer moving parts.

### 5.3 Worker Pool

**Responsibility:** Picks jobs off the queue and runs them through the pipeline: fetch → transcribe → classify → extract → store.

**Concurrency:** 2–4 workers is plenty. Bottleneck is Claude API rate and Whisper transcription time, not CPU.

**Pipeline stages (per item):**

**Stage 1 — Fetch media.** Download the media (video for reels, image(s) for posts, carousel) and metadata (caption, hashtags, author, post date, original poster's bio if available, like count). Store media in S3 with a deterministic key: `s3://recall-media/{media_pk}/{filename}`. Store the metadata in `saved_items`.

**Stage 2 — Transcribe (reels only).** Run Whisper on the audio track. Use `whisper.cpp` or `faster-whisper` for speed; `large-v3` if accuracy matters, `small` if cost matters. Store transcript in `saved_items.transcript`. Skip if not a reel.

**Stage 3 — Classify.** Send caption + transcript + first-frame image (multimodal) to Claude with a classification prompt. Output is one of: `EDUCATIONAL`, `EVENT`, `RECIPE`, `TRAVEL`, `TECH_REFERENCE`, `OTHER`. (Categories: per your spec — Educational, Events, Recipes, Travel, Tech/product references. `OTHER` catches everything that doesn't fit.) Save to `saved_items.category`. Confidence score stored too.

**Stage 4 — Extract.** Based on classification, run a **category-specific extraction prompt** that returns a strict JSON schema. Schema per category below in §6. Store JSON in `extractions.payload`.

**Stage 5 — Embed.** Generate an embedding of `caption + transcript + extracted_text_summary` using `text-embedding-3-small` or whatever's cheapest at decent quality. Store in `embeddings.vector` (pgvector). Used for semantic search.

**Stage 6 — Finalize.** Set `saved_items.status = COMPLETED`. Worker acks the queue. Job done.

**Error handling:** Each stage has its own retry policy. Whisper failure on one item shouldn't poison the whole pipeline; mark item as `FAILED_TRANSCRIBE` and continue. Dashboard surfaces failures.

### 5.4 LLM Layer — classification & extraction

Two prompts, both calling Claude API.

**Classifier prompt (short, single call):**
- Inputs: caption text, transcript (if reel), first-frame description (optional, multimodal).
- Output: `{"category": "RECIPE", "confidence": 0.93, "reasoning": "..." }`
- Temperature: 0. JSON mode.

**Extractor prompts (one per category, chosen based on classifier output):**

Each extractor returns a strict JSON object conforming to that category's schema (§6). All extractors share boilerplate: "extract only what's present, don't hallucinate, leave fields null if not stated."

`ASSUMPTION:` Claude Sonnet for both. Haiku is too thin for nuanced extraction; Opus is overkill and expensive.

### 5.5 FastAPI Backend

**Surface (REST, JSON):**

- `GET /items` — list saved items with filters: `?category=`, `?date_from=`, `?date_to=`, `?search=` (semantic search via embedding), `?status=`, paginated.
- `GET /items/{id}` — single item with full extraction.
- `GET /items/{id}/media` — signed S3 URL for the original media.
- `POST /items/{id}/recategorize` — manual override of category; triggers re-extract.
- `DELETE /items/{id}` — remove from index (does not unsave on Instagram; clarify in UI).
- `GET /stats` — counts per category, recent activity, failed items.
- `POST /actions/event/{id}/add-to-calendar` — generates `.ics` and returns it (or pushes to a calendar via Google Calendar API if connected). See §8 for "actions."
- `POST /poller/resume` — admin: resume poller after a challenge.
- `GET /health` — health check for ALB / monitoring.

**Auth:**
- Single-user version (personal): a single shared secret in a header (`X-API-Key`), validated by FastAPI middleware. Stored in env. Dashboard injects it from a server-side config.
- `ASSUMPTION:` Single-user. The spec is structured so multi-tenant could be bolted on later (each row in `saved_items` already has implicit user scope; you'd add a `user_id` column and OAuth), but V1 doesn't bother.

### 5.6 Next.js Dashboard

**Pages:**

- **Home / feed:** scrollable feed of all saved items, newest first. Each card shows: thumbnail, category badge, key extracted fields (e.g., for an event: title + date + venue), caption excerpt, "View Details" button. Filters in the header: category dropdown, search bar, date range.
- **Item detail:** full media player (video or image), full caption, transcript with timestamps (clickable to seek video), full extraction JSON rendered as a nice readable card, "Actions" sidebar (add to calendar, copy recipe to clipboard, open original on Instagram, mark archived).
- **Category views:** /events, /recipes, /travel, /educational, /tech — each with category-specific rendering. E.g., /events shows a calendar-style layout; /recipes is a grid of recipe cards.
- **Search:** full-text + semantic combined. Show why a result matched (which field).
- **Settings:** Instagram credentials status (logged in / needs challenge), poller controls, API key management, LLM cost dashboard (total spend, items processed), data export.
- **Failed items:** list of items that failed processing, with retry buttons.

**Styling:**
- `ASSUMPTION:` Tailwind + shadcn/ui. Standard, fast, looks good.
- Dark mode default since most of your screenshots are dark.

`ASSUMPTION:` Web-only. No Android companion in V1. Web dashboard is responsive and works on mobile browsers fine. You can install it as a PWA on your phone if you want app-like access. Flag if you want a native Android app — it's a separate ~2-week project.

---

## 6. Data model

Postgres. Tables:

### `saved_items`

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `media_pk` | text UNIQUE | Instagram's internal ID. Primary dedup key. |
| `media_type` | enum | `POST`, `REEL`, `CAROUSEL`, `IGTV` |
| `instagram_url` | text | Permalink to the original post |
| `author_username` | text | |
| `author_full_name` | text | |
| `caption` | text | |
| `hashtags` | text[] | Parsed from caption |
| `post_created_at` | timestamptz | When the post was originally posted |
| `saved_at` | timestamptz | When YOU saved it (best-effort from API; falls back to ingestion time) |
| `ingested_at` | timestamptz | When the poller picked it up |
| `category` | enum | One of the 5 categories or `OTHER` or `PENDING` |
| `category_confidence` | float | From classifier |
| `transcript` | text | Null for non-reels |
| `transcript_lang` | text | ISO code; whisper auto-detects |
| `status` | enum | `PENDING`, `FETCHING`, `TRANSCRIBING`, `CLASSIFYING`, `EXTRACTING`, `COMPLETED`, `FAILED_*` |
| `error_log` | jsonb | If failed, what happened at which stage |
| `archived` | bool | User-archived; hidden from default views |

### `extractions`

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `item_id` | UUID FK → saved_items | |
| `schema_version` | text | For when you change schemas |
| `payload` | jsonb | The category-specific extraction. Schema below. |
| `created_at` | timestamptz | |

### `media_refs`

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `item_id` | UUID FK → saved_items | |
| `s3_key` | text | `recall-media/{media_pk}/{filename}` |
| `media_kind` | enum | `VIDEO`, `IMAGE`, `THUMBNAIL`, `AUDIO_EXTRACT` |
| `bytes` | bigint | |

### `embeddings`

| column | type | notes |
|---|---|---|
| `item_id` | UUID FK → saved_items, UNIQUE | one embedding per item |
| `vector` | vector(1536) | pgvector |
| `model` | text | Track which model generated it (for re-embedding when models change) |

### Per-category extraction schemas (the JSON in `extractions.payload`)

**EDUCATIONAL**
```json
{
  "topic": "string",
  "key_takeaways": ["string"],
  "concepts_introduced": ["string"],
  "tools_or_resources_mentioned": [{"name": "string", "url_or_handle": "string|null"}],
  "difficulty": "beginner|intermediate|advanced|null",
  "summary": "string (2-3 sentences)"
}
```

**EVENT**
```json
{
  "title": "string",
  "event_type": "concert|meetup|conference|festival|workshop|other",
  "starts_at": "ISO datetime|null",
  "ends_at": "ISO datetime|null",
  "venue_name": "string|null",
  "venue_address": "string|null",
  "city": "string|null",
  "country": "string|null",
  "rsvp_url": "string|null",
  "ticket_url": "string|null",
  "price_info": "string|null",
  "summary": "string"
}
```

**RECIPE**
```json
{
  "dish_name": "string",
  "cuisine": "string|null",
  "servings": "number|null",
  "prep_time_minutes": "number|null",
  "cook_time_minutes": "number|null",
  "ingredients": [{"item": "string", "quantity": "string|null", "notes": "string|null"}],
  "steps": ["string"],
  "tips": ["string"],
  "dietary_tags": ["vegetarian|vegan|gluten-free|..."]
}
```

**TRAVEL**
```json
{
  "destination": "string",
  "country": "string|null",
  "city": "string|null",
  "best_time_to_visit": "string|null",
  "places_mentioned": [{"name": "string", "type": "restaurant|hotel|attraction|...", "notes": "string"}],
  "tips": ["string"],
  "budget_info": "string|null",
  "summary": "string"
}
```

**TECH_REFERENCE**
```json
{
  "subject": "string",
  "tools_mentioned": [{"name": "string", "url": "string|null", "category": "string"}],
  "code_or_command_snippets": [{"language": "string", "snippet": "string", "purpose": "string"}],
  "key_insights": ["string"],
  "comparisons_made": [{"between": ["string"], "verdict": "string"}],
  "summary": "string"
}
```

**OTHER**
```json
{
  "summary": "string",
  "notable_text": "string|null",
  "tags": ["string"]
}
```

---

## 7. Data flow / sequence

### Happy path (new saved item):

1. You save a reel on Instagram (just tap the bookmark icon).
2. Within 5 minutes, Poller's next tick runs `account_saved_medias()`.
3. Diff against `saved_items.media_pk`. New item detected. Insert row with `status=PENDING`. Enqueue job.
4. Worker picks up job. Sets `status=FETCHING`. Downloads media + metadata via `instagrapi`. Uploads to S3. Inserts `media_refs` rows.
5. Worker sets `status=TRANSCRIBING`. Extracts audio. Runs Whisper. Updates `saved_items.transcript`.
6. Worker sets `status=CLASSIFYING`. Calls Claude with classifier prompt. Sets `saved_items.category`.
7. Worker sets `status=EXTRACTING`. Picks the right extractor based on category. Calls Claude. Inserts `extractions` row.
8. Worker generates embedding. Inserts `embeddings` row.
9. Worker sets `status=COMPLETED`. Acks queue.
10. Next time you open the dashboard, the item is there with full extraction.

### Search flow:

1. You type "that Tokyo ramen place" in dashboard search bar.
2. Frontend hits `GET /items?search=that+tokyo+ramen+place`.
3. Backend embeds the query, runs pgvector similarity search, and also does a simple text match on captions/extractions. Combines results, ranks them.
4. Returns top 20. Dashboard renders.

### Action flow (e.g., add event to calendar):

1. You're viewing an event item. Click "Add to Calendar."
2. Frontend hits `POST /actions/event/{id}/add-to-calendar`.
3. Backend reads the extraction JSON, constructs an `.ics` file, returns it (or, if Google Calendar OAuth is connected in Settings, calls the Calendar API directly).
4. Dashboard either downloads the `.ics` or shows "added to calendar."

---

## 8. External dependencies — what each one does and why

| Dependency | Purpose | Why this one |
|---|---|---|
| `instagrapi` | Read Instagram Saved collection, download media | Most actively maintained unofficial IG library; covers Collections endpoint; MIT-licensed |
| `yt-dlp` | Fallback media downloader if `instagrapi` download fails | Industry standard; handles Instagram URLs well |
| Whisper (`faster-whisper` or `whisper.cpp`) | Reel audio → transcript | Local processing, no audio leaves your infra |
| Claude API (Anthropic) | Classification + per-category extraction | Best structured JSON extraction; you already have access |
| OpenAI Embeddings API | Generate embeddings for semantic search | Cheap (`text-embedding-3-small`); could swap to local `bge-small` if you want zero-cloud |
| PostgreSQL + pgvector | Primary store + vector search | One database, fewer moving parts than separate Postgres + Qdrant |
| AWS S3 | Media storage | Standard, cheap |
| AWS SQS | Job queue | Free at this volume, scales if needed |
| AWS EC2 (single t3.medium) or ECS | Compute | Cheap; t3.medium handles polling + 2 workers + API comfortably |
| Next.js | Dashboard | Modern, deployable to Vercel free tier or self-hosted next to backend |
| Tailwind + shadcn/ui | UI styling | Fast to build, looks decent without design work |

**Cost estimate at personal usage (~50 saved items / week):**
- Whisper local: $0 (CPU time, baked into EC2)
- Claude API: ~$0.01–$0.03 per item (classify + extract), so ~$0.50–$1.50/week
- Embeddings: negligible
- AWS: ~$15–25/month (t3.medium + RDS db.t4g.micro + S3 + SQS)
- **Total: ~$20–30/month** — that's the actual cost of running this for yourself

---

## 9. Open questions Claude Code should ask before starting

When you hand this to Claude Code, expect it to ask:

1. **Burner Instagram account vs. main?** (Affects ban risk + how you "save" things — burner means re-saving everything from a follow-yourself setup.)
2. **Poller location:** AWS or your home network? (Affects detection risk.)
3. **Whisper model size?** `small` (fast, ~$0 cost, decent for English) vs. `large-v3` (slow, best quality, multilingual). Default `small`; revisit if transcript quality is bad on regional language reels.
4. **OAuth Google Calendar integration in V1?** Or just `.ics` download for events? Default `.ics` only; OAuth is +0.5 day if you want it.
5. **Embedding model?** OpenAI cloud or local `bge-small`? Default OpenAI; trivial to swap.
6. **Are you single-user only or want multi-user-ready schema from day 1?** Default single-user; multi-tenant is a future migration.
7. **Custom categories?** The five listed cover your ask. Want to add (e.g.) "Fitness," "Fashion," "Memes"? Add the schema, add the prompt; ~1 hour each.

---

## 10. Risks and how we handle them

| Risk | Mitigation |
|---|---|
| Instagram bans the poller account | Use burner account, conservative polling, residential IP, session reuse. Document this prominently in README. |
| `instagrapi` breaks when Instagram changes endpoints | It happens; the library updates within days usually. Pin a version; track upstream. |
| Claude API costs spike | Hard daily spend limit in backend code; alert when approaching. Monthly budget cap of ~$20. |
| Whisper transcription quality bad for regional languages | Make model size configurable; document upgrade path to `large-v3`. |
| User saves an item, deletes it before poller picks it up | We just don't capture it. Acceptable for V1. |
| Extraction is wrong (LLM hallucinates dates/places) | "Recategorize" button on every item; manual edit of extraction JSON in detail view. |
| Media in S3 grows unbounded | Configurable retention policy: keep originals for N days, then keep only thumbnail + transcript. Default: keep forever. |
| Open-source means people might use it badly (spam, etc.) | README is explicit: personal-use, your own account, your own AWS, your responsibility. Not your problem after that. |

---

## 11. README content for the public repo

When you ship this open-source, the README should cover:

1. What it does (the 3-bullet wedge from §3)
2. **One-paragraph honest comparison to ReelRecall, Dewey, Alf, Bookmarkjar** — so people understand the wedge and why they'd use yours
3. Setup: clone, fill `.env`, `docker-compose up`, log into Instagram on first run (Settings page), done
4. **Big honest warning section on Instagram TOS and account-ban risk** — be explicit, recommend burner account, don't pretend it's risk-free
5. Architecture diagram (same as §4)
6. Extending: how to add a new category, how to swap the LLM, how to swap the embedding model
7. License: MIT
8. "This is a personal project, not a service. PRs welcome but no SLA, no support."

## 12. What "done" means for V1

You can demo this video:

1. Open Instagram on your phone, save a reel about ramen in Tokyo
2. Open Instagram, save a reel about a music festival happening in November
3. Open Instagram, save a tutorial about Postgres replication
4. Cut to dashboard 5 minutes later. All three items present. Each shows the right category. Click the ramen one — full transcript, restaurant name extracted, location extracted. Click the festival one — date, venue, ticket link extracted, "Add to Calendar" button. Click the tutorial one — Postgres commands extracted as code snippets, key insights bulleted.
5. Search bar: type "asian food" — both the ramen reel and (if relevant) other food saves show up via semantic match, not keyword match.

That's V1 done. Everything beyond that — Android app, multi-user, automatic recipe meal planning, event RSVP automation, advanced LLM cost analytics — is V2+.

---

## 13. Things explicitly out of scope for V1

- Native Android app (web PWA only)
- Multi-user / cloud signup
- Sharing collections with other users
- Browser extension for one-click save while browsing IG on desktop
- Integration with other platforms (TikTok, YouTube Shorts, X bookmarks) — that's a roadmap item, not V1
- Auto-tagging custom user-defined tags
- AI-suggested actions ("you saved 5 ramen places — should I make you a Tokyo ramen tour itinerary?") — cool but V2
- Notifications when something interesting is added
- Backfill of historical saved items beyond what `instagrapi` exposes from the API in one pass

---
