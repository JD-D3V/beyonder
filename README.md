# Beyonder

Multi-agent LangGraph system for Chinese web-novel translation and Q&A, with public reading and invite-only accounts. Glossary-RAG over Qdrant enforces consistent xianxia terminology across chapters. Spoiler-aware retrieval blocks future-chapter leakage. Knowledge graph view of characters, sects, and realms.

## Why

Machine translation of Chinese web novels breaks every chapter: 渡劫 becomes "cross robbery" then "tribulation" then "calamity-crossing" in 50 pages. DeepL gets ~41% term consistency on a 500-term gold set; Beyonder gets ~89% by locking the glossary at every translation call.

## Stack (zero cost)

| Layer | Pick | Free tier |
|---|---|---|
| LLM | Gemini (`gemini-3.6-flash` by default, `GEMINI_MODEL`); also OpenRouter, Groq, DeepSeek, OpenAI via bring-your-own-key | Gemini: free key, no card |
| Embeddings | Local fastembed, `paraphrase-multilingual-MiniLM-L12-v2` (384 dims) | Free, runs in-process, no API |
| Vector DB | Qdrant (local Docker) | Unlimited local |
| Relational | Postgres + pgvector (Docker) | Unlimited local |
| Orchestrator | LangGraph | OSS |
| Backend | FastAPI | OSS |
| Frontend | Next.js 15 (static export, built inside Docker) | OSS |
| Icons | Aria Icons (Lucide, ISC), vendored as source | OSS |

## What changed in v2

- **Public reading.** Novels, chapters, glossary, graph and review flags are readable without an account.
- **Invite-only accounts.** Library shelves, reading progress, ingest, translate and Q&A need a login. Sign-up requires an invite code.
- **Single admin.** One owner account, created from the command line. Only the admin edits or deletes novels, resolves review flags and issues invites.
- **Bring your own key.** Users add their own AI provider and key in Settings. The key stays in the browser and is sent per request. The server's `GEMINI_API_KEY` is used only for the admin.
- **Review queue.** The critic fixes known glossary drift and queues non-blocking review flags instead of retrying.
- **Glossary seed.** A starter xianxia glossary is seeded into each novel before extraction.
- **PDF import** alongside .txt, .md and .epub.

## Getting a free Gemini key

1. Open https://aistudio.google.com/apikey and sign in with a Google account.
2. Create an API key (no card needed).
3. In the app, open Settings, choose provider `gemini`, and paste the key. Or, for the admin on a self-hosted instance, put it in `.env` as `GEMINI_API_KEY`.

Other providers (OpenRouter, Groq, DeepSeek, OpenAI) work the same way: pick the provider in Settings and paste its key.

## Security posture

npm has been under active supply-chain attack (Shai-Hulud worm, malicious postinstall packages). Beyonder's frontend tooling never runs on the host:

- All `pnpm`/`node` work happens inside a Docker container with `--ignore-scripts` and a frozen lockfile.
- The container has no host filesystem access outside `frontend/`.
- Production deploy serves a static export — no Node runtime in prod.
- Backend stays Python-only, no npm anywhere in the request path.

See [docs/security.md](docs/security.md) for the full hardening checklist.

## Quick start

macOS / Linux (needs python3 and Docker Desktop or OrbStack; `make doctor` checks):

```sh
make up        # copies .env.example to .env if missing, starts Postgres + Qdrant
make migrate   # schema (creates backend/.venv and installs deps)
make admin     # creates the owner account from ADMIN_EMAIL / ADMIN_PASSWORD in .env
make backend   # FastAPI on http://localhost:8000
make frontend  # Next.js in Docker on http://localhost:3000 (npm never on the host)
```

Windows (PowerShell):

```powershell
Copy-Item .env.example .env   # then set ADMIN_EMAIL and ADMIN_PASSWORD
.\run.ps1 up
.\run.ps1 migrate
.\run.ps1 admin
.\run.ps1 backend
.\run.ps1 frontend
```

`make doctor` / `.\run.ps1 doctor` check the toolchain. `.\run.ps1 api` runs the same
container image production runs, against the local database. `make test` runs pytest.

### First admin and inviting users

1. Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` (8+ characters) in `.env`, then run `make admin` (or `.\run.ps1 admin`). It refuses if an admin already exists.
2. Sign in on the site as the admin.
3. Create an invite: `POST /admin/invites` (admin session required, optional body `{"days": N}`); the response is `{"code": "..."}`. `GET /admin/invites` lists them. Send the code to the new user; they use it on the sign-up page.
4. After upgrading from v1 (embedding dimension 768 to 384), run `make reembed` (or `.\run.ps1 reembed`) to rebuild the Qdrant collection.

URL ingestion uses a plain HTTP fetch by default. For sites that render
chapters in JavaScript, install the browser once and switch backends:

```powershell
.\backend\.venv\Scripts\python.exe -m playwright install chromium
# then set SCRAPER_BACKEND=playwright (or auto) in .env
```

## Deploy

Four free services, no credit card: Render for the API, Supabase for Postgres,
Qdrant Cloud for vectors, GitHub Pages for the static frontend. Step by step in
[docs/deploy.md](docs/deploy.md).

Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` on the deployed API and run `create_admin` once; accounts are invite-only and reading is public. Details in [docs/deploy.md](docs/deploy.md).

## Features

- **Ingestion**: URL scrape (SSRF-guarded; plain HTTP or Playwright), .txt/.md/.epub/.pdf upload, auto chapter split, language detect.
- **Glossary-RAG**: Extracts named entities per chapter, embeds source terms, locks translations.
- **Translator agent**: Looks up glossary before each paragraph, coins new terms with confidence scores.
- **Critic agent**: Re-reads output, fixes known glossary drift and queues non-blocking review flags (no retries).
- **Q&A agent**: Spoiler-filtered retrieval — chunks past `current_chapter` are dropped before answering.
- **Knowledge graph**: Per-novel character/sect/realm graph with spoiler-aware filter.
- **Eval harness**: 50 Q&A gold, 500-term gold, DeepL baseline. `pytest eval/` for CI.

## Eval

```powershell
cd backend
python -m eval.run qa        # Q&A accuracy + spoiler leakage rate
python -m eval.run translate # term consistency vs DeepL
python -m eval.run all       # writes eval/reports/latest.json
```

Target: 85%+ Q&A accuracy, 0% spoiler leakage, 85%+ term consistency.

## Project layout

```
beyonder/
  backend/
    app/
      ingest/        # scraper, epub loader, lang detect, chunker
      embed/         # local fastembed embeddings + Qdrant client
      storage/       # SQLAlchemy models, repositories
      agents/        # extractor, translator, critic, qa
      graph/         # LangGraph orchestrator
      llm/           # providers, client, per-request key resolution
      auth/          # passwords, sessions, deps
      glossary/      # xianxia seed
      review/        # critic flag checks
      kg/            # relation extraction + graph queries
      api/           # routes: novels, translate, reader, library, auth_routes
      scripts/       # create_admin, reembed
      common/        # config, logging, rate limit
    eval/
      gold/          # 50 Q&A + 500-term gold sets
    tests/
    scripts/         # seed, smoke-test
  frontend/          # Next.js 15, built in Docker only
  infra/
    postgres/        # init.sql, pgvector setup
  docker-compose.yml
```

## Icons

Icons come from Aria Icons (Lucide, ISC license), fetched as plain SVG data by `frontend/scripts/fetch-icons.sh` and vendored as source. The aria-icons CLI is not run (see [docs/security.md](docs/security.md)).

## License

Personal use. Don't redistribute scraped novels.
