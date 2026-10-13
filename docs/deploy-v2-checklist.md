# Deploying v2 (redo/wtr-style → main)

Do these in order. Steps 1–3 happen **before** merging; the merge triggers Render's auto-deploy and
the GitHub Pages build.

## 1. Check locally first
- `make up && make migrate && make backend` and `make frontend`, then click through: sign in, Settings
  (public name, API key), a novel page (reviews, cover upload, Translate titles), the reader
  (Google/Gemini/Source/Both, settings panel, infinite mode, Listen, comments), Rankings, Admin
  (invites, reports), Import (file, URL, table-of-contents).
- `cd backend && TEST_DATABASE_URL=postgresql://beyonder:beyonder@localhost:5433/beyonder_test .venv/bin/python -m pytest -q`
- `make frontend-build`

## 2. Back up production data
- Supabase: Database → Backups (or `pg_dump "$DATABASE_URL" > backup.sql`).
- Migration `0005_accounts` **deletes existing user rows** (v1 had only a demo user). Reading progress
  from v1 is not carried over.

## 3. Render environment (Dashboard → beyonder-api → Environment)
| Key | Value |
|---|---|
| `API_TOKEN` | **remove** (the shared token gate is gone) |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | your admin login (password ≥ 8 chars) |
| `TRUST_PROXY_HOPS` | `1` — then verify (step 6) |
| `MT_PROVIDER` | `google_free` (default), `libretranslate`, or `off` |
| `MT_RPS` | `0.2` recommended on a server (one Google request per 5 s; fewer blocks) |
| `AUTO_COVERS` | `true` |
| `AUTO_UPDATE_HOURS` | `0` (off) or e.g. `24` |
| `SCRAPER_BACKEND` | `http` (no headless browser on Render) |
| `CORS_ORIGINS` | your Pages origin, e.g. `https://jd-d3v.github.io` |
| `GEMINI_API_KEY` | admin-only; only you can use it |
Remove `GEMINI_EMBED_MODEL` if present (embeddings are local now).

## 4. Merge
Merge the pull request into `main`. Render redeploys the API; the Pages workflow rebuilds the site.

## 5. One-off commands (Render Shell, in `/app`)
```
alembic upgrade head                      # 0004 … 0018
python -m app.scripts.reembed             # recreates the Qdrant collection at 384 dims
python -m app.scripts.create_admin        # uses ADMIN_EMAIL / ADMIN_PASSWORD
python -m app.scripts.seed_classics --max-chapters 30
python -m app.scripts.fill_covers
```
Machine translation of new books then runs in the background (watch the logs for `mt.`).

## 6. Verify on the live site
- `/health` returns 200; the catalog loads; covers show.
- Sign in as admin, create an invite, sign up in a private window with it.
- Proxy hops: sign in once, check the API log line for the client IP. If every request shows the same
  internal address, increase `TRUST_PROXY_HOPS`; if it shows your real IP, it's right.
- Memory: Render → Metrics. The local embedding model adds ~200 MB; if the instance restarts with
  out-of-memory, the free 512 MB tier is too small (upgrade, or set a smaller embedding model).

## Known limits
- The unofficial Google endpoint is blocked intermittently; translation pauses and resumes on its own.
  Switch `MT_PROVIDER` if it stays blocked.
- Free web translation in the browser needs desktop Chrome; other browsers show the source text.
