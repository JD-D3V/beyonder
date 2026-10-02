# Architecture

```
[User browser]
     │
     ▼ http (CORS allows :3000)
[Next.js static export served from Docker dev / FastAPI in prod]
     │
     ▼ JSON
[FastAPI on :8000]
     │
     ├──► [auth: session bearer token; reading routes are public]
     │
     ├──► [LangGraph orchestrator]
     │         │   load → seed → extract → translate → critic(flags) → relations → persist
     │         │
     │         ├─ load (Postgres)
     │         ├─ seed (starter xianxia glossary)
     │         ├─ extract (LLM, JSON schema)
     │         ├─ translate (LLM, glossary-locked)
     │         ├─ critic (deterministic drift fix + review flags, no retry loop)
     │         ├─ relations (LLM, KG extraction)
     │         └─ persist (Postgres + Qdrant)
     │
     ├──► [Q&A]
     │      ├─ embed query (local fastembed)
     │      ├─ Qdrant vector search w/ spoiler filter (chapter_idx ≤ user.current)
     │      └─ Gemini Flash w/ grounded prompt + citations
     │
     └──► [KG view]
            └─ Postgres adjacency query, filtered by user's current_chapter
```

## Data flow

1. **Ingest** (`POST /novels/ingest/text` or `/url`)
   - Detect lang, split chapters, insert into `chapters` table.
2. **Embed** (`POST /novels/embed`)
   - Chunk each chapter, embed locally (fastembed, 384 dims), upsert into Qdrant.
3. **Translate** (`POST /translate`) — LangGraph pipeline:
   - Pull existing glossary entries with `first_chapter ≤ current_chapter`.
   - Extractor proposes new terms.
   - Translator translates paragraph by paragraph, looking up locked terms.
   - Critic applies deterministic glossary-drift fixes and queues non-blocking review flags (`review_flags`). No retry loop.
   - Relations agent populates KG edges.
   - Persist: upsert terms, translations, relations.
4. **Ask** (`POST /ask`)
   - Embed question locally.
   - Qdrant search with `novel_id ∧ chapter_idx ≤ current_chapter`.
   - Top-K chunks → grounded prompt → Gemini → answer + citations.

## Why these choices

- **Gemini Flash** has a free tier large
  enough (1500 RPD) to translate dozens of chapters during evaluation without
  a paywall.
- **Qdrant local Docker** beats a managed cloud free tier on iteration speed.
  Switch to Qdrant Cloud or Supabase pgvector at deploy by changing the env
  vars; the `Vector` column on `terms` means we can also do glossary
  semantic search directly in Postgres if Qdrant becomes the bottleneck.
- **LangGraph** gives a linear, inspectable pipeline with per-node state
  (LangSmith optional). The critic no longer loops; problems become review
  flags a human resolves.
- **Local embeddings** (fastembed, `paraphrase-multilingual-MiniLM-L12-v2`,
  384 dims) mean no embedding API to retire or rate-limit. Changing the model
  or dimension requires `python -m app.scripts.reembed`.
- **Static-export frontend** keeps prod off the npm runtime, so the eventual
  threat model only covers build-time supply chain.

## Auth and key resolution

- Accounts are invite-only. The single admin is created by
  `python -m app.scripts.create_admin`; the admin issues invites via
  `POST /admin/invites`. Login returns a session bearer token (`SESSION_DAYS`).
- Reading (novels, chapters, glossary, graph, flags) is public; library,
  progress, ingest, translate and Q&A need a session; edit/delete novels,
  resolve flags and invites need admin.
- LLM credentials are resolved per request in `app/llm/resolve.py` from the
  `X-LLM-Provider`, `X-LLM-Key` and `X-LLM-Model` headers. A user key always
  wins. With no key, only an admin on Gemini falls back to the server's
  `GEMINI_API_KEY`; everyone else gets `402 llm_key_required`.

## Module map

| Path | Job |
|---|---|
| `backend/app/common/` | config, logging (key redaction), rate limiter |
| `backend/app/llm/` | provider table, OpenAI-compatible client, per-request key resolution |
| `backend/app/auth/` | password hashing, sessions, auth dependencies |
| `backend/app/glossary/` | starter xianxia glossary seed |
| `backend/app/review/` | critic checks that produce review flags |
| `backend/app/scripts/` | `create_admin`, `reembed` |
| `backend/app/storage/` | SQLAlchemy models, repository helpers |
| `backend/app/ingest/` | scraper, EPUB/TXT loaders, lang detect, chapter splitter, chunker |
| `backend/app/embed/` | local fastembed model, Qdrant store, end-to-end embed pipeline |
| `backend/app/agents/` | extractor / translator / critic / qa / relation prompts + logic |
| `backend/app/graph/` | LangGraph orchestrator |
| `backend/app/kg/` | KG query helpers |
| `backend/app/api/` | FastAPI routes split into `novels`, `translate`, `reader`, `library`, `auth_routes` + Pydantic schemas |
| `backend/eval/` | gold sets + CLI runner + metric helpers |
| `backend/migrations/` | Alembic |
| `frontend/app/` | Next.js App Router pages (home, reader, glossary, kg, eval) |
| `frontend/components/` | shared UI (Nav) |
| `frontend/lib/` | API client types |

## Capacity bands (free tier)

| Resource | Free cap | Headroom |
|---|---|---|
| Gemini Flash gen | 1500 RPD, 1M TPM, 15 RPM | ≈ 250 chapters/day at 6 calls/chapter |
| Local embeddings | CPU-bound, no quota | no API calls |
| Qdrant local | bound by disk | ≈ 5M chunks/GB |
| Postgres local | bound by disk | one novel ≈ a few MB |
| Vercel hobby (if you ever deploy frontend there) | 100 GB/mo bandwidth | demo-friendly |
