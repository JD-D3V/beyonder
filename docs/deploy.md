# Deploy guide

The supported production layout is four free services, no credit card:

| Piece | Host | Free tier |
|---|---|---|
| API (FastAPI container) | Render | 512 MB instance, sleeps after 15 min idle |
| Postgres | Supabase | 500 MB, pgvector preinstalled |
| Vectors | Qdrant Cloud | 1 GB cluster |
| Frontend (static export) | GitHub Pages | unlimited public sites |

Everything below assumes the repo is on GitHub, because Render and Pages both
deploy from it.

---

## 1. Postgres on Supabase

1. Create a project at https://supabase.com. Save the database password.
2. Project settings -> Database -> Connection string -> **Session pooler**.
   Use that URI, not the direct one: direct `db.PROJECT.supabase.co` is
   IPv6-only and Render cannot reach it. The pooler host looks like
   `aws-0-us-east-1.pooler.supabase.com:5432` with user `postgres.PROJECT`.
3. Put it in your local `.env` as `DATABASE_URL`.

The app rewrites the URI on the way in: it pins the psycopg v3 driver and adds
`sslmode=require` for any non-local host, so paste the plain `postgresql://`
string as given.

## 2. Vectors on Qdrant Cloud

1. Create a free cluster at https://cloud.qdrant.io.
2. Copy the cluster URL and an API key into `.env` as `QDRANT_URL` and
   `QDRANT_API_KEY`. The collection is created on first embed.

## 3. Migrate the database

Run this once from your machine, against the cloud database:

```powershell
.\run.ps1 migrate
```

It reads `DATABASE_URL` from `.env`. Re-run it after every new Alembic
revision; nothing in the deployed container migrates on boot.

## 4. API on Render

1. https://render.com -> New -> Blueprint -> pick this repo. Render reads
   [`render.yaml`](../render.yaml).
2. Fill in the five values marked "sync: false":
   `GEMINI_API_KEY`, `DATABASE_URL`, `QDRANT_URL`, `QDRANT_API_KEY`,
   `CORS_ORIGINS`.
3. `CORS_ORIGINS` is your Pages origin with no trailing slash and no path,
   for example `https://jd-d3v.github.io`. Comma-separate to add more.
4. `API_TOKEN` is the shared secret that keeps the library private. Generate
   one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   Leave it unset and the API is open to anyone who finds the URL, which on a
   public site means anyone: the API address is compiled into the page.

   The token is never built into the frontend, because a static site cannot
   hold a secret. The first time a browser hits the API it gets a 401 and the
   site asks for the token, then keeps it in that browser's local storage. Each
   device unlocks once. To revoke access, change the value here and every
   browser is locked out at its next request.

   `/health` stays open so the platform healthcheck keeps working, and CORS
   preflights are never challenged, because a browser sends those before it is
   allowed to attach the header.
4. Deploy. Health is `GET /health`; interactive docs are at `/docs`.

Note the service URL, e.g. `https://beyonder-api.onrender.com`.

`GET /health` reports which build answered, so a stale deploy is obvious:

```json
{"ok": true, "commit": "abd2d80", "model": "gemini-3.6-flash", "embed_model": "gemini-embedding-001"}
```

If `commit` lags the repo, the service did not redeploy. If `embed_model`
is not what render.yaml says, the dashboard holds an older value: blueprint
edits do not overwrite env vars that already exist on the service. Fix it in
the dashboard.

**The free instance sleeps.** After 15 idle minutes the next request takes
about 50 seconds to wake it. The frontend will look frozen on that first call.

## 5. Frontend on GitHub Pages

1. Repo -> Settings -> Pages -> Source: **GitHub Actions**.
2. Repo -> Settings -> Secrets and variables -> Actions -> Variables, add:
   - `NEXT_PUBLIC_API_URL` = your Render URL, no trailing slash.
   - `NEXT_PUBLIC_BASE_PATH` = `/beyonder`, the repo name, because a project
     site is served from a sub-path. Leave empty for a user site or a custom
     domain.
3. Push to `main`, or run the "Deploy frontend to GitHub Pages" workflow by
   hand. It builds the static export with `--ignore-scripts` in CI, so npm
   still never runs on your machine.

The site lands at `https://<user>.github.io/beyonder/`.

Both values are compiled into the bundle at build time. Changing either one
means re-running the workflow, not restarting anything.

### Cloudflare Pages instead

Same export, different host, and you get a root path so `NEXT_PUBLIC_BASE_PATH`
stays empty. Build locally and upload:

```powershell
$env:NEXT_PUBLIC_API_URL="https://beyonder-api.onrender.com"
.\run.ps1 frontend-build     # writes frontend/out/
```

Drag `frontend/out` into a Cloudflare Pages direct upload. Add the new origin
to `CORS_ORIGINS` on Render.

---

## Fully local instead

No accounts, nothing public:

```powershell
.\run.ps1 doctor      # check toolchain
.\run.ps1 up          # Postgres + Qdrant in Docker
.\run.ps1 migrate     # apply Alembic migrations
.\run.ps1 backend     # uvicorn on :8000, or: .\run.ps1 api for the real image
.\run.ps1 frontend    # Next dev server in Docker on :3000
```

`.\run.ps1 api` builds and runs the same container Render runs, wired to the
local Postgres and Qdrant. Use it to reproduce a production problem.

## Before the first real request

Set `GEMINI_API_KEY` (free, no card, https://aistudio.google.com/apikey).
Without it, ingestion works but translation, embedding, and Q&A all fail.

```powershell
.\run.ps1 smoke      # fabricated demo novel, end-to-end through Gemini
```

## Operating notes

- **Scraping.** The deployed API runs `SCRAPER_BACKEND=http`: one plain fetch,
  no browser, because Chromium does not fit in a 512 MB instance. Sites that
  build their chapters in JavaScript come back empty there. Run locally with
  `SCRAPER_BACKEND=auto` and `playwright install chromium` for those, or
  upload the text directly.
- **Models get retired.** Google has already retired both original defaults
  (`text-embedding-004`, then `gemini-2.5-flash`) for newly issued keys, and
  the failure is a 404 at call time, not at boot. If translation or Q&A starts
  answering "couldn't reach the model", list what the key can actually use:

  ```powershell
  .\backend\.venv\Scripts\python.exe -c "import google.generativeai as g, os; g.configure(api_key=os.environ['GEMINI_API_KEY']); [print(m.name) for m in g.list_models()]"
  ```

  Then set `GEMINI_MODEL` / `GEMINI_EMBED_MODEL` in `.env` and on Render.
- **Translating a long book.** Use "translate all" on the book page. It runs
  small batches and saves each chapter as it lands, so stopping, closing the
  tab or losing the connection never discards finished work; reopening and
  pressing it again picks up from the first untranslated chapter. It is not
  fast: each chapter costs four model calls (extract, translate, critic,
  relations) and the rate limiter spaces them, so budget roughly a minute per
  chapter on the free tier.
- **Rate limits.** Gemini free tier is 15 requests/minute and 1500/day. The
  limiter in `app/common/rate_limit.py` respects `GEMINI_RPM_LIMIT`. A long
  novel will take hours, by design.
- **Backups.** Supabase snapshots the database. Locally, `data/postgres/` and
  `data/qdrant/` are bind mounts; tar them.
- **Rotating the Gemini key.** Change it in the Render dashboard; the service
  restarts itself. Locally, edit `.env` and restart the backend.
- **Eval dashboard.** `/eval/latest` is 404 until you run
  `python -m eval.run all` once, which writes `eval/reports/latest.json`.
  That file is not in the image, so the deployed dashboard stays empty unless
  you commit a report.
- **Bumping deps.** See [security.md](security.md). The frontend lockfile is
  regenerated inside a container, never on the host.
