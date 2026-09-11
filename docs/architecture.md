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
     ├──► [LangGraph orchestrator]
     │         │
     │         ├─ load (Postgres)
     │         ├─ extract (Gemini Flash, JSON schema)
     │         ├─ translate (Gemini Flash, JSON schema, glossary-locked)
     │         ├─ critic (deterministic + LLM fix loop, ≤2 retries)
     │         ├─ relations (Gemini Flash, KG extraction)
     │         └─ persist (Postgres + Qdrant)
     │
     ├──► [Q&A]
     │      ├─ embed query (Gemini embeddings)
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
   - Chunk each chapter, embed with `text-embedding-004`, upsert into Qdrant.
3. **Translate** (`POST /translate`) — LangGraph pipeline:
   - Pull existing glossary entries with `first_chapter ≤ current_chapter`.
   - Extractor proposes new terms.
   - Translator translates paragraph by paragraph, looking up locked terms.
   - Critic does deterministic glossary-drift check; LLM-suggests a fix when violations found; retries up to 2x.
   - Relations agent populates KG edges.
   - Persist: upsert terms, translations, relations.
4. **Ask** (`POST /ask`)
   - Embed question (`RETRIEVAL_QUERY` task type).
   - Qdrant search with `novel_id ∧ chapter_idx ≤ current_chapter`.
   - Top-K chunks → grounded prompt → Gemini → answer + citations.

## Why these choices

- **Gemini 2.5 Flash** is the only mainstream LLM with a free tier large
  enough (1500 RPD) to translate dozens of chapters during evaluation without
  a paywall.
- **Qdrant local Docker** beats a managed cloud free tier on iteration speed.
  Switch to Qdrant Cloud or Supabase pgvector at deploy by changing the env
  vars; the `Vector(768)` column on `terms` means we can also do glossary
  semantic search directly in Postgres if Qdrant becomes the bottleneck.
- **LangGraph** lets us encode the critic retry loop as a conditional edge
  instead of imperative `for retries in range(2):` — easier to inspect for
  evals (LangSmith optional).
- **Static-export frontend** keeps prod off the npm runtime, so the eventual
  threat model only covers build-time supply chain.

## Module map

| Path | Job |
|---|---|
| `backend/app/common/` | config, logging, rate limiter |
| `backend/app/storage/` | SQLAlchemy models, repository helpers |
| `backend/app/ingest/` | scraper, EPUB/TXT loaders, lang detect, chapter splitter, chunker |
| `backend/app/embed/` | Gemini wrapper, Qdrant store, end-to-end embed pipeline |
| `backend/app/agents/` | extractor / translator / critic / qa / relation prompts + logic |
| `backend/app/graph/` | LangGraph orchestrator |
| `backend/app/kg/` | KG query helpers |
| `backend/app/api/` | FastAPI routes + Pydantic schemas |
| `backend/eval/` | gold sets + CLI runner + metric helpers |
| `backend/migrations/` | Alembic |
| `frontend/app/` | Next.js App Router pages (home, reader, glossary, kg, eval) |
| `frontend/components/` | shared UI (Nav) |
| `frontend/lib/` | API client types |

## Capacity bands (free tier)

| Resource | Free cap | Headroom |
|---|---|---|
| Gemini Flash gen | 1500 RPD, 1M TPM, 15 RPM | ≈ 250 chapters/day at 6 calls/chapter |
| `text-embedding-004` | unlimited (no card) | embed 5k chunks ≈ 5 min |
| Qdrant local | bound by disk | ≈ 5M chunks/GB |
| Postgres local | bound by disk | one novel ≈ a few MB |
| Vercel hobby (if you ever deploy frontend there) | 100 GB/mo bandwidth | demo-friendly |
