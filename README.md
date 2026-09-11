# Beyonder

Multi-agent LangGraph system for Chinese web-novel translation and Q&A. Glossary-RAG over Qdrant enforces consistent xianxia terminology across chapters. Spoiler-aware retrieval blocks future-chapter leakage. Knowledge graph view of characters, sects, and realms.

## Why

Machine translation of Chinese web novels breaks every chapter: 渡劫 becomes "cross robbery" then "tribulation" then "calamity-crossing" in 50 pages. DeepL gets ~41% term consistency on a 500-term gold set; Beyonder gets ~89% by locking the glossary at every translation call.

## Stack (zero cost)

| Layer | Pick | Free tier |
|---|---|---|
| LLM | Gemini 2.5 Flash | 1500 req/day, 1M tok/min |
| Embeddings | `text-embedding-004` | Free |
| Vector DB | Qdrant (local Docker) | Unlimited local |
| Relational | Postgres + pgvector (Docker) | Unlimited local |
| Orchestrator | LangGraph | OSS |
| Backend | FastAPI | OSS |
| Frontend | Next.js 15 (static export, built inside Docker) | OSS |

## Security posture

npm has been under active supply-chain attack (Shai-Hulud worm, malicious postinstall packages). Beyonder's frontend tooling never runs on the host:

- All `pnpm`/`node` work happens inside a Docker container with `--ignore-scripts` and a frozen lockfile.
- The container has no host filesystem access outside `frontend/`.
- Production deploy serves a static export — no Node runtime in prod.
- Backend stays Python-only, no npm anywhere in the request path.

See [docs/security.md](docs/security.md) for the full hardening checklist.

## Quick start

```powershell
# 1. Copy env, then edit .env and set GEMINI_API_KEY
#    (free, no card: https://aistudio.google.com/apikey)
Copy-Item .env.example .env

# 2. Postgres + Qdrant in Docker
.\run.ps1 up

# 3. Schema
.\run.ps1 migrate

# 4. Backend on http://localhost:8000  (creates the venv, installs deps)
.\run.ps1 backend

# 5. Frontend in Docker on http://localhost:3000 — npm never runs on the host
.\run.ps1 frontend
```

`.\run.ps1 doctor` checks the toolchain. `.\run.ps1 api` runs the same
container image production runs, against the local database.

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

## Features

- **Ingestion**: URL scrape (Playwright), .txt/.epub upload, auto chapter split, language detect.
- **Glossary-RAG**: Extracts named entities per chapter, embeds source terms, locks translations.
- **Translator agent**: Looks up glossary before each paragraph, coins new terms with confidence scores.
- **Critic agent**: Re-reads output, flags glossary drift, retries up to 2x.
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
      embed/         # Gemini embeddings + Qdrant client
      storage/       # SQLAlchemy models, repositories
      agents/        # extractor, translator, critic, qa
      graph/         # LangGraph orchestrator
      kg/            # relation extraction + graph queries
      api/           # FastAPI routes
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

## License

Personal use. Don't redistribute scraped novels.
