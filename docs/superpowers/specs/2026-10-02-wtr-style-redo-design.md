# Beyonder v2: WTR-LAB-style reading site — design

Date: 2026-10-02 · Branch: `redo/wtr-style`

## Goal

Turn Beyonder from a single-user, token-gated library into a public reading
site in the style of WTR-LAB: anyone can browse and read translated novels;
signed-in readers keep their own place in each book and ask spoiler-safe AI
questions; translation is paid for by whoever runs it, with their own key.

Keep the existing stack and as much code as possible: FastAPI, LangGraph,
Postgres + pgvector, Qdrant, Next.js static export, Render / GitHub Pages.

## Decisions (agreed in chat)

| Topic | Decision |
|---|---|
| Access | Reading is public, no account needed. Accounts are invite-only. |
| Admin | Exactly one admin (the owner). The admin's Gemini key in `.env` is used **only** for actions the admin performs. Never for anyone else, no allowance (deferred). |
| Other users' AI | Bring your own key. Kept in the user's browser only, sent per request, never stored or logged by the server. |
| Providers | Gemini, OpenRouter, Groq, DeepSeek, OpenAI — any OpenAI-compatible endpoint. |
| Contributed translations | Saved straight into the shared library (option A). Weak output is caught by the review queue; admin can re-translate. |
| v1 features | A catalog, B personal library shelves, C reader settings. Ratings/comments/rankings later. |
| Books in | URL scrape (exists), EPUB/TXT (exists), PDF (new). |

## Out of scope for v1

Admin-key allowance for others; server-side storage of user keys; background
batch jobs that outlive the tab; ratings, reviews, comments, rankings;
"community vs official" translation labels; email verification / password
reset by email (admin resets passwords).

## Architecture changes

### 1. Accounts and auth (`backend/app/auth/`, replaces `common/auth.py` gate)

- Tables: `users` (rework existing: `email`, `password_hash`, `is_admin`,
  `created_at`; drop `handle`/`progress_json` after migrating data),
  `sessions` (opaque random token hashed with SHA-256, `user_id`,
  `expires_at`), `invites` (code, created_by, used_by, expires_at).
- Passwords hashed with `argon2-cffi`.
- Sign-in returns a bearer session token; the frontend keeps it in
  localStorage (frontend and API are on different origins, so cross-site
  cookies are unreliable). Same pattern as today's `TokenGate`.
- Admin bootstrap: `python -m app.scripts.create_admin` reads
  `ADMIN_EMAIL`/`ADMIN_PASSWORD` from env. Only one admin may exist.
- FastAPI dependencies: `current_user_optional`, `current_user`, `require_admin`.
- `API_TOKEN` middleware is removed; public GET routes become open.

Route access:

| Route group | Who |
|---|---|
| `GET /novels*`, chapters, translations, glossary, kg, flags (read) | anyone |
| progress, library shelves, `/ask`, translate, import | signed-in user |
| delete novel, edit glossary, resolve flags, invites, re-translate over existing | admin |

### 2. Per-account reading position

- New table `reading_progress(user_id, novel_id, chapter_idx, updated_at)`,
  PK `(user_id, novel_id)`. Migrate existing `progress_json` rows.
- `/ask`, `/kg`, glossary views read `current_chapter` from this table for
  signed-in users. The client can no longer pass an arbitrary
  `current_chapter` to `/ask`; the server uses the stored one.
- Anonymous readers: position in localStorage only; no `/ask`.
- Reading a chapter while signed in advances progress to that chapter
  (never moves it backwards automatically).

### 3. Bring-your-own-key LLM layer (`backend/app/llm/`)

- `LLMClient(provider, api_key, model)` — one class, async `httpx` against
  the OpenAI-compatible `/chat/completions` endpoint of each provider
  (Gemini exposes one). Methods: `generate(prompt, system, ...)`,
  `generate_json(prompt, schema, ...)` (uses `response_format` json_schema
  when the provider supports it, falls back to json_object + Pydantic
  validation).
- Provider registry: base URL + default model per provider.
- Key resolution per request (`resolve_llm(request, user)`):
  - headers `X-LLM-Provider`, `X-LLM-Key`, optional `X-LLM-Model` → user key;
  - else if user is admin → server `GEMINI_API_KEY`;
  - else → 402-style error "add your own API key in Settings".
  The server key is **never** reachable by non-admin users.
- Rate limiting keyed per API key (hash), not process-wide.
- Keys never appear in logs: structlog processor redacts `x-llm-key`.
- Replaces `embed/gemini.py` generation; `google-generativeai` is removed
  (it configures one global key per process, unsafe for BYOK).
- Agents (`translator`, `extractor`, `critic`, `qa`, `relation`) take an
  `LLMClient` argument instead of calling `get_gemini()`. Prompts unchanged.
- We deliberately avoid `litellm` (large dependency surface, past PyPI
  supply-chain incident) in line with `docs/security.md`.

### 4. Local embeddings (no key needed)

- Chapter chunks and Q&A queries are embedded with `fastembed` (ONNX, CPU)
  using a small multilingual model (target:
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-dim;
  confirm it is in fastembed's supported list at implementation).
- `EMBEDDING_DIM` becomes 384; Qdrant collection is recreated; `terms.embedding`
  column migrated to `Vector(384)`. A `reembed` script rebuilds vectors.
- Ingest therefore costs nobody's key.

### 5. Glossary pipeline (lncrawl-translator + OpenTranslator ideas)

- Every translate call loads the novel's glossary (terms with
  `first_chapter ≤ chapter`) and injects it — already true; keep.
- **Seed dictionary**: `backend/app/glossary/seed_xianxia.yaml` — common
  cultivation/cultural terms (realms, titles, honorifics, techniques) with
  standard renderings. Matched by substring against source text before the
  extractor runs; hits are added with `confidence=0.9`, `notes="seed"`.
- Translate responses return `new_terms: [...]` alongside the text.
- Glossary entries gain `locked: bool` (admin-locked terms are never
  overwritten by the extractor) and `added_by` (user id or null).

### 6. Non-blocking review queue

- New table `review_flags(id, novel_id, chapter_idx, kind, source_span,
  target_span, note, status, created_at, resolved_by)`; kind ∈
  `glossary_drift | unknown_name | pronoun | idiom | untranslated`.
- Critic stops retrying in a loop. Pipeline becomes
  `load → seed → extract → translate → critic(flag) → relations → persist`.
  Critic runs the existing deterministic drift check plus one LLM pass that
  returns flags; flags are persisted; the translation is saved regardless.
  One automatic fix is applied only for deterministic glossary drift
  (string replace of the drifted rendering), no LLM retry.
- `untranslated` = leftover CJK characters in output (deterministic).
- Reader shows a small flag marker; admin page lists open flags per novel.

### 7. Ingestion

- PDF via `pypdf` (BSD license; avoid AGPL `pymupdf`). Text extracted per
  page, joined, passed to the existing splitter.
- Signed-in users may import; admin may delete. Imports need no AI key
  (embedding is local).

### 8. Frontend (Next.js static export, keep pages, add/rework)

- **Catalog** (`/`): search by title/author, filter by tag/status/length,
  sort by updated / new / chapter count. Backed by `GET /novels` query
  params (server-side filtering).
- **Novel page** (`/novel`): cover, metadata, chapter list with
  translated/untranslated markers, "Continue reading", "Add to shelf".
- **Library** (`/library`, new): shelves Reading / Plan to read / Completed
  via new table `library_entries(user_id, novel_id, shelf, updated_at)`;
  continue-reading list from `reading_progress`.
- **Reader** (`/reader`): prev/next, settings panel (font family, size,
  line height, width, theme light/sepia/dark) in localStorage; glossary
  terms highlighted with hover definitions; "Translate this chapter" button
  if signed in and untranslated (uses resumable `/translate/step`).
- **Account** (`/login`, `/settings`): sign in, invite sign-up, API key
  form (provider, key, model) stored in localStorage, with a short guide to
  getting a free Google AI Studio key.
- `TokenGate` is removed; `lib/api.ts` sends session token + LLM headers.

### 9. Dev tooling

- `Makefile` for macOS/Linux mirroring `run.ps1` (up, migrate, backend,
  frontend, test). README updated (model names, auth, BYOK).

## Error handling

- Missing key → `402 {"detail": "...", "code": "llm_key_required"}`; the
  frontend shows "Add your API key" linking to Settings.
- Provider 401/403 → `400 llm_key_invalid`; 429 → `429 llm_rate_limited`,
  never retried more than the existing tenacity policy.
- Partial resumable translations survive provider errors (existing).

## Testing

- Unit: password hashing, session lifecycle, invite use, access matrix per
  route group, key resolution (non-admin can never get server key), log
  redaction, LLMClient request shape (httpx mock), seed matcher, critic
  flags, PDF loader, progress never auto-decreases.
- Existing 62 tests must keep passing (updated where APIs change).
- DB-backed tests run when Postgres is available (existing `test_db.py`
  pattern); local Docker is currently not installed on the dev machine.
- Frontend verified via Docker build (`make frontend-build`) once Docker is
  available — npm never runs on the host (docs/security.md).

## Rollout order

1. Auth + accounts + progress table (backend)
2. LLM layer + local embeddings + agent refactor
3. Glossary seed + review queue
4. PDF ingest + catalog/library API
5. Frontend: auth/settings, catalog, novel, library, reader
6. Makefile + docs
