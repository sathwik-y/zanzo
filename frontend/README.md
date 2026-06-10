# Zanzo — Dashboard (frontend)

The web dashboard for [Zanzo](https://github.com/sathwik-y/zanzo), the Instagram saved-reels organizer. *Zanzō (残像)* — "afterimage": the image that lingers after the thing is gone.

This is the **frontend only**. It talks to the Zanzo backend (FastAPI) through a server-side proxy so the backend API key never reaches the browser. The backend, pipeline and infrastructure live in the main repo: **https://github.com/sathwik-y/zanzo**.

## Stack

- Next.js 16 (App Router), React 19
- Tailwind CSS, dark-mode by default
- lucide-react icons

## Pages

- **Feed** — all saved items, newest first, with search (semantic + text) and category filters
- **Item detail** — media player, click-to-seek transcript, per-category extraction, Resources panel, auto-engagement status, actions (add-to-calendar, copy recipe, archive, recategorize, retry)
- **Category views** — `/category/events|recipes|travel|educational|tech|other`
- **Settings** — poller health + resume, AI spend, library breakdown, auto-engagement caps editor
- **Failed** — items that errored in processing, with retry

## Run it

Point it at a running Zanzo backend (default `http://localhost:8000`).

```bash
cp .env.example .env.local      # set BACKEND_URL and BACKEND_API_KEY
npm install
npm run dev                     # http://localhost:3000
```

`BACKEND_API_KEY` must match the `API_KEY` configured on the backend. It is read
server-side only (in `app/api/backend/[...path]/route.ts`) and is never exposed
to the client.

## Build

```bash
npm run build && npm start
```

A `Dockerfile` is included (standalone output) for container deployments.
