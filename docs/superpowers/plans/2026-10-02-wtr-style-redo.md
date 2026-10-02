# Beyonder v2 (WTR-style) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Public WTR-LAB-style reading site with invite-only accounts, per-account reading position, spoiler-safe Q&A, bring-your-own-key AI, a shared glossary with seed terms, and a non-blocking review queue.

**Architecture:** Keep FastAPI + LangGraph + Postgres/pgvector + Qdrant + static Next.js. Replace the process-global Gemini SDK with a per-request OpenAI-compatible `LLMClient`; replace Gemini embeddings with local `fastembed`; replace the shared-token gate with session auth and per-route dependencies.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, LangGraph, httpx, argon2-cffi, fastembed, pypdf, Next.js 15 static export.

**Spec:** `docs/superpowers/specs/2026-10-02-wtr-style-redo-design.md` — read it before every task.

## Global Constraints

- The server `GEMINI_API_KEY` is used **only** when the signed-in user `is_admin`. No other code path may reach it.
- User API keys are never stored server-side and never logged (header `x-llm-key` redacted).
- No `litellm`, no `pymupdf` (AGPL), no `google-generativeai` at the end of Task 3.
- All new deps pinned with `==` in `backend/requirements.txt`; dev-only deps in `requirements-dev.txt`.
- npm/pnpm never run on the host (docs/security.md). Frontend is verified only through the Docker build.
- Embedding dimension: 384. Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (if fastembed does not list it, use the closest listed multilingual 384-dim model and note it in the commit).
- Migrations are sequential: `20261002_0004` … `20261002_0007`, each `down_revision` the previous.
- Tests that need Postgres are marked `@pytest.mark.db` and skip unless `TEST_DATABASE_URL` is set. Everything else must run with no services.
- Run tests from `backend/`: `.venv/bin/python -m pytest`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A non-admin request with `X-LLM-Provider` but empty `X-LLM-Key` while `GEMINI_API_KEY` is set must get `402 llm_key_required`, not the server key → test in Task 1.
- A user key must not appear in logs or in error `detail` when the provider returns 401/500 → test in Task 1.
- `/ask` body carrying `current_chapter` larger than the stored progress must answer from the stored value → test in Task 5.
- A non-admin translating a chapter that already has a complete translation must not overwrite it → test in Task 5.
- Two concurrent `LLMClient`s with different keys must each send their own `Authorization` header → test in Task 1.

---

### Task 1: Per-request LLM client and key resolution

**Files:**
- Create: `backend/app/llm/__init__.py`, `backend/app/llm/providers.py`, `backend/app/llm/client.py`, `backend/app/llm/resolve.py`
- Modify: `backend/app/common/logging.py` (add redaction processor), `backend/app/common/rate_limit.py` (keyed limiter)
- Test: `backend/tests/test_llm_client.py`, `backend/tests/test_llm_resolve.py`

**Interfaces:**
- Produces:
  - `providers.PROVIDERS: dict[str, Provider]`, `Provider(name: str, base_url: str, default_model: str, supports_json_schema: bool)`. Entries: `gemini` (`https://generativelanguage.googleapis.com/v1beta/openai`, `settings.gemini_model`, True), `openrouter` (`https://openrouter.ai/api/v1`, `deepseek/deepseek-chat-v3.1:free`, False), `groq` (`https://api.groq.com/openai/v1`, `llama-3.3-70b-versatile`, False), `deepseek` (`https://api.deepseek.com/v1`, `deepseek-chat`, False), `openai` (`https://api.openai.com/v1`, `gpt-4.1-mini`, True).
  - `class LLMError(RuntimeError)` with `code: str` in `{"llm_key_invalid","llm_rate_limited","llm_upstream"}`.
  - `class LLMClient(provider: str, api_key: str, model: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None)` with attribute `model_name: str` and methods
    `async generate(prompt: str, *, system: str | None = None, temperature: float = 0.2, max_output_tokens: int = 4096) -> str` and
    `async generate_json(prompt: str, *, schema: dict, system: str | None = None, temperature: float = 0.1, max_output_tokens: int = 4096) -> Any` — same signatures the agents already call on `GeminiClient`.
  - `resolve.resolve_llm(headers: Mapping[str, str], user: User | None) -> LLMClient` raising `HTTPException(402, {"code": "llm_key_required", ...})`.
  - `rate_limit.limiter_for(key_id: str) -> AsyncRateLimiter` (one bucket per sha256(api_key)[:16]).

- [ ] **Step 1: Write failing tests** in `test_llm_client.py` using `httpx.MockTransport`:
  - `test_sends_bearer_key_and_model` — request URL ends `/chat/completions`, header `authorization == "Bearer k1"`, JSON body `model` equals provider default.
  - `test_two_clients_do_not_share_keys` — two clients `k1`/`k2` run concurrently via `asyncio.gather`; each recorded request carries its own key.
  - `test_generate_json_parses_fenced_json` — response content "```json\n{\"a\":1}\n```" → `{"a": 1}`.
  - `test_json_schema_only_when_supported` — `gemini` body has `response_format.type == "json_schema"`; `groq` body has `response_format.type == "json_object"`.
  - `test_401_maps_to_key_invalid_without_leaking_key` — upstream 401 → `LLMError.code == "llm_key_invalid"` and `"k1" not in str(err)`.
  - `test_429_maps_to_rate_limited`.
  - `test_redaction_processor_hides_llm_key` — processor turns `{"x-llm-key": "k1", "api_key": "k1"}` into `"***"` values.
- [ ] **Step 2: Write failing tests** in `test_llm_resolve.py` (use a simple `User`-like object with `is_admin`):
  - `test_user_key_header_wins` → client with provider/key from headers, model from `X-LLM-Model` when given.
  - `test_admin_without_header_gets_server_key` (monkeypatch `settings.gemini_api_key = "srv"`) → `api_key == "srv"`, provider `gemini`.
  - `test_non_admin_without_key_gets_402_even_if_server_key_set`.
  - `test_provider_without_key_gets_402` (header provider set, key empty, user non-admin).
  - `test_anonymous_gets_402`.
  - `test_unknown_provider_gets_400`.
- [ ] **Step 3: Run** `.venv/bin/python -m pytest tests/test_llm_client.py tests/test_llm_resolve.py` — expect FAIL (module not found).
- [ ] **Step 4: Implement.** `LLMClient` builds a fresh `httpx.AsyncClient` per call (or per instance) with `Authorization: Bearer <key>`; wraps the call in `limiter_for(...)`; retries `llm_rate_limited`/`llm_upstream` with the existing tenacity policy (3 attempts, exp backoff 2–30 s); error messages contain status code and provider, never the key. Redaction processor is added to the structlog chain in `logging.py`.
- [ ] **Step 5: Run the two test files** — expect PASS. Run the full suite — 62 existing tests still PASS.
- [ ] **Step 6: Commit** `feat(llm): per-request OpenAI-compatible client with BYOK resolution`.

### Task 2: Local embeddings

**Files:**
- Create: `backend/app/embed/local.py`, `backend/migrations/versions/20261002_0004_local_embeddings.py`, `backend/app/scripts/reembed.py`
- Modify: `backend/app/embed/pipeline.py`, `backend/app/common/config.py` (`embedding_dim = 384`, add `embed_model_name`), `backend/requirements.txt` (`fastembed==<latest 0.x>`), `backend/Dockerfile` (pre-download model at build so cold start is offline)
- Test: `backend/tests/test_embed_local.py`

**Interfaces:**
- Produces: `local.embed_texts(texts: Sequence[str]) -> list[list[float]]` (sync, model loaded lazily once), `async pipeline.embed_chapters(novel_id: int, chapters: Sequence[Chapter]) -> int` and `async pipeline.embed_query(query: str) -> list[float]` keep their current signatures but no longer touch Gemini (run `embed_texts` via `asyncio.to_thread`).
- Migration 0004: drop and re-add `terms.embedding` as `Vector(384)` (values are rebuilt by `reembed`).
- `python -m app.scripts.reembed [--novel ID]` recreates the Qdrant collection with dim 384 and re-embeds chapters.

- [ ] **Step 1: Write failing tests:** `test_pipeline_uses_local_embedder` (monkeypatch `local.embed_texts` to return `[[0.0]*384]`; `embed_query("q")` returns length 384 and Gemini is never imported/called); `test_embed_texts_real_model` marked `@pytest.mark.slow` asserting `len(vec) == 384` and two near-identical sentences have cosine > 0.8.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** and add `slow` marker to `pytest.ini` (`addopts` excludes nothing; slow test runs when the model is cached).
- [ ] **Step 4: Run** full suite + `-m slow` once — PASS.
- [ ] **Step 5: Commit** `feat(embed): local fastembed embeddings, no API key needed`.

### Task 3: Agents and graph take an injected LLMClient

**Files:**
- Modify: `backend/app/agents/{translator,extractor,critic,qa,relation}.py`, `backend/app/graph/orchestrator.py`, `backend/app/graph/resumable.py`, `backend/app/embed/__init__.py`, `backend/requirements.txt`, `backend/eval/run.py`, `backend/app/main.py` (startup log)
- Delete: `backend/app/embed/gemini.py`; remove `google-generativeai` from requirements
- Test: `backend/tests/test_agents_llm.py`

**Interfaces:**
- Consumes: `LLMClient` (Task 1).
- Produces: every agent function's `client` parameter becomes required and typed `LLMClient` (keyword name unchanged). `run_translation_graph(*, llm: LLMClient, novel_id, novel_title, source_lang, target_lang, chapter_idx) -> TranslateState` passes the client as `config={"configurable": {"llm": llm}}`; nodes read it with `config["configurable"]["llm"]`. `translate_step(*, llm: LLMClient, novel_id, chapter_idx, target_lang="en", time_budget_s=STEP_BUDGET_S) -> StepResult`. Persisted `Translation.model` = `llm.model_name`.

- [ ] **Step 1: Write failing tests** with a `FakeLLM` (records prompts, returns canned JSON): `test_translate_chapter_uses_given_client`, `test_resumable_step_uses_given_client` (monkeypatch DB helpers as `test_resumable.py` does), `test_no_module_imports_google_generativeai` (walk `app/` source, assert the string `google.generativeai` is absent).
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**; update `test_resumable.py` call sites for the new `llm` kwarg.
- [ ] **Step 4: Run** full suite — PASS.
- [ ] **Step 5: Commit** `refactor(agents): inject LLMClient; drop google-generativeai`.

### Task 4: Accounts, sessions, invites

**Files:**
- Create: `backend/app/auth/__init__.py`, `backend/app/auth/passwords.py`, `backend/app/auth/sessions.py`, `backend/app/auth/deps.py`, `backend/app/api/auth_routes.py`, `backend/app/scripts/create_admin.py`, `backend/migrations/versions/20261002_0005_accounts.py`
- Modify: `backend/app/storage/models.py` (User rework; add `Session`, `Invite`, `ReadingProgress`, `LibraryEntry`), `backend/app/storage/repository.py` (replace handle/progress_json helpers), `backend/app/main.py` (remove `TokenAuthMiddleware`, include auth router, allow `PATCH`/`DELETE` in CORS), `backend/app/common/config.py` (drop `api_token`; add `admin_email`, `admin_password`, `session_days = 30`), `.env.example`
- Delete: `backend/app/common/auth.py`, `backend/tests/test_auth.py` (replaced)
- Test: `backend/tests/test_accounts.py`, `backend/tests/test_accounts_db.py` (`@pytest.mark.db`)

**Interfaces:**
- Models: `User(id, email unique lowercased, password_hash, is_admin bool default False, created_at)`; `Session(token_hash str(64) PK, user_id FK, expires_at)`; `Invite(code str PK, created_by FK, used_by FK nullable, expires_at)`; `ReadingProgress(user_id, novel_id, chapter_idx, updated_at)` PK `(user_id, novel_id)`; `LibraryEntry(user_id, novel_id, shelf in {"reading","plan","completed"}, updated_at)` PK `(user_id, novel_id)`; `Translation.translated_by: int | None` (FK users, `ondelete="SET NULL"`).
- Migration 0005: create tables; old `users` rows with `handle` → kept only if an admin is later matched (simplest: drop `handle`/`progress_json`, keep no legacy users — v1 had a single demo user; note this in the migration docstring).
- `passwords.hash_password(pw: str) -> str`, `passwords.verify_password(pw: str, hashed: str) -> bool` (argon2-cffi).
- `sessions.new_token() -> str` (`secrets.token_urlsafe(32)`), `sessions.hash_token(t: str) -> str` (sha256 hex), `sessions.create_session(s, user) -> str`, `sessions.user_for_token(s, token) -> User | None` (None if expired), `sessions.revoke(s, token) -> None`.
- `deps.current_user_optional(request) -> User | None`, `deps.current_user -> User` (401), `deps.require_admin -> User` (403). Token read from `Authorization: Bearer`.
- Routes: `POST /auth/login {email,password} -> {token, user}`, `POST /auth/signup {email,password,invite} -> {token, user}`, `POST /auth/logout`, `GET /auth/me -> {id,email,is_admin}`, `POST /admin/invites {days=7} -> {code}` (admin), `GET /admin/invites` (admin).
- `create_admin`: refuses if an admin exists; reads `ADMIN_EMAIL`/`ADMIN_PASSWORD`.

- [ ] **Step 1: Failing tests (no DB):** `test_password_roundtrip`, `test_wrong_password_rejected`, `test_token_hash_is_sha256_hex`, `test_me_without_token_is_401` (TestClient), `test_admin_route_as_non_admin_is_403` (override `current_user` dep with a non-admin), `test_public_health_needs_no_token`.
- [ ] **Step 2: Failing DB tests:** `test_signup_requires_unused_unexpired_invite`, `test_invite_single_use`, `test_expired_session_is_401`, `test_logout_revokes`, `test_create_admin_refuses_second_admin`, `test_email_case_insensitive_login`.
- [ ] **Step 3: Run** — FAIL (DB tests SKIP without `TEST_DATABASE_URL`).
- [ ] **Step 4: Implement.** Login error message is identical for unknown email and wrong password.
- [ ] **Step 5: Run** full suite — PASS.
- [ ] **Step 6: Commit** `feat(auth): invite-only accounts with bearer sessions`.

### Task 5: Route access, per-account progress, BYOK wiring

**Files:**
- Split `backend/app/api/router.py` into `backend/app/api/novels.py` (catalog/novel/chapter/ingest/delete/patch), `backend/app/api/translate.py` (translate, batch, step), `backend/app/api/reader.py` (progress, ask, glossary, kg); `router.py` keeps `/health`, `/eval/latest` and includes the three. Schemas stay in `schemas.py`.
- Modify: `backend/app/storage/repository.py` (`get_progress(s, user_id, novel_id) -> int`, `advance_progress(s, user_id, novel_id, idx) -> int` — never decreases, `set_progress(s, user_id, novel_id, idx)` — explicit, may decrease)
- Test: `backend/tests/test_access.py`, `backend/tests/test_reader_db.py` (`db`)

**Interfaces:**
- Consumes: deps (Task 4), `resolve_llm` (Task 1), new graph signatures (Task 3).
- Access matrix exactly as spec §1. `GET /novels/{id}/chapters/{idx}` with a signed-in user calls `advance_progress`.
- `GET /progress?novel_id=` and `POST /progress {novel_id, current_chapter}` now use the account (no `handle`).
- `POST /ask {novel_id, question}` — any `current_chapter` in the body is ignored; server uses `get_progress`.
- `/glossary` and `/kg`: `up_to` query param still accepted; when absent and user signed in, default to stored progress; anonymous default stays 100000 (public, reader's choice).
- `/translate*`: `llm = resolve_llm(request.headers, user)`. If a complete translation exists and user is not admin → return existing (`/translate`) or `409 already_translated` (`/translate/step` start). Admin may pass `force=true` to overwrite.
- Set `translations.translated_by` (column added in Task 4) to the requesting user's id on every write.
- LLMError → HTTP: `llm_key_invalid` 400, `llm_rate_limited` 429, `llm_upstream` 502, body `{"detail": ..., "code": ...}`.

- [ ] **Step 1: Failing tests (no DB, dependency overrides + monkeypatched repo calls):** `test_anonymous_can_list_novels`, `test_anonymous_cannot_translate_401`, `test_user_without_key_translate_402`, `test_non_admin_delete_403`, `test_ask_ignores_client_current_chapter` (stub `get_progress` → 3, stub `answer_question` and assert it received `current_chapter=3` when body sent 99), `test_non_admin_cannot_overwrite_complete_translation`.
- [ ] **Step 2: Failing DB tests:** `test_reading_advances_but_never_rewinds`, `test_set_progress_can_rewind`.
- [ ] **Step 3: Run** — FAIL. **Step 4: Implement.** **Step 5: Run** full suite — PASS.
- [ ] **Step 6: Commit** `feat(api): public reading, account progress, BYOK translate`.

### Task 6: Glossary seed, locked terms, new_terms in responses

**Files:**
- Create: `backend/app/glossary/__init__.py`, `backend/app/glossary/seed.py`, `backend/app/glossary/seed_xianxia.yaml` (~150 entries: realms 炼气/筑基/金丹/元婴/化神…, titles 师尊/师兄/长老/宗主…, terms 灵气/丹田/渡劫/法宝…, each `{source, target, kind}`), `backend/migrations/versions/20261002_0006_glossary.py`
- Modify: `models.Term` (+`locked: bool default False`, +`added_by: int | None FK users`), `repository.upsert_terms` (never overwrite `locked` rows), orchestrator (new `seed` node between `load` and `extract`), `schemas.TranslateResult` / `TranslateStepResult` (+`new_terms: list[GlossaryEntryOut]`), novels API: `PATCH /novels/{id}/glossary/{term_id} {target_term?, locked?}` (admin)
- Requirements: `pyyaml==6.0.2` if not already present
- Test: `backend/tests/test_glossary_seed.py`

**Interfaces:**
- `seed.load_seed() -> list[SeedTerm]` (cached), `seed.match_seed(text: str, known_sources: set[str]) -> list[dict]` returning term dicts shaped like extractor output with `confidence=0.9`, `notes="seed"`, `first_chapter` set by caller. Longest-match-first so 金丹期 wins over 金丹.

- [ ] **Step 1: Failing tests:** `test_seed_yaml_loads_and_has_no_duplicate_sources`, `test_match_prefers_longest`, `test_match_skips_known`, `test_upsert_does_not_overwrite_locked` (`db`).
- [ ] **Step 2–4:** run FAIL → implement → run PASS (full suite).
- [ ] **Step 5: Commit** `feat(glossary): xianxia seed terms, locked entries, new_terms in responses`.

### Task 7: Non-blocking review queue

**Files:**
- Create: `backend/app/review/__init__.py`, `backend/app/review/checks.py`, `backend/migrations/versions/20261002_0007_review_flags.py`
- Modify: `models.py` (+`ReviewFlag`), `agents/critic.py` (flag mode), `agents/prompts.py` (critic prompt returns flags with kinds `unknown_name|pronoun|idiom`; bump `CRITIC_VERSION`), orchestrator (remove retry edge: `translate → critic → relate → persist`; drop `critic_max_retries` setting), `graph/resumable.py` (run deterministic checks on completion), reader API: `GET /novels/{id}/flags?status=open&chapter=` (public), `POST /flags/{id}/resolve` (admin)
- Test: `backend/tests/test_review.py`

**Interfaces:**
- `ReviewFlag(id, novel_id, chapter_idx, kind, source_span, target_span, note, status "open"|"resolved", created_at, resolved_by)`.
- `checks.untranslated_spans(text: str) -> list[str]` (runs of ≥2 CJK chars), `checks.fix_glossary_drift(source: str, candidate: str, glossary: list[tuple[str,str]], variants: dict[str, list[str]]) -> tuple[str, list[dict]]` — replaces a known wrong rendering (from `variants`, built from earlier flags/extractor alternates) with the locked target; returns fixed text and drift flags for anything it could not fix.
- `critique_translation(...) -> CritiqueResult` gains `flags: list[dict]`; never triggers a retranslation.

- [ ] **Step 1: Failing tests:** `test_untranslated_detects_cjk_runs`, `test_single_cjk_punctuation_not_flagged`, `test_drift_fix_replaces_variant`, `test_graph_has_no_retry_edge` (inspect compiled graph edges), `test_critic_llm_failure_still_saves_translation` (FakeLLM raises → state.translation non-empty, flags contain only deterministic ones).
- [ ] **Step 2–4:** run FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(review): non-blocking QA flags replace critic retry loop`.

### Task 8: PDF import, catalog query, library shelves API

**Files:**
- Create: `backend/app/ingest/pdf_loader.py`, `backend/app/api/library.py`
- Modify: `novels.py` upload route (accept `.pdf`), `repository.library_rows` (filters), `GET /novels` query params, `requirements.txt` (`pypdf==<latest 5.x>`)
- Test: `backend/tests/test_pdf_loader.py` (build a 2-page PDF in-test with `pypdf`'s writer or a tiny committed fixture `tests/fixtures/two_pages.pdf`), `backend/tests/test_catalog.py`

**Interfaces:**
- `pdf_loader.load_pdf(path: str | Path) -> str` — pages joined with `\n\n`; raises `ValueError("PDF has no extractable text (scanned?)")` when empty.
- `GET /novels?q=&tag=&status=&min_chapters=&max_chapters=&sort=updated|new|chapters&limit=50&offset=0` — `q` matches title or author case-insensitively.
- `GET /library` (user) → shelves with novel summaries + `current_chapter`; `PUT /library/{novel_id} {shelf}`; `DELETE /library/{novel_id}`.

- [ ] **Step 1: Failing tests:** `test_pdf_text_extracted`, `test_empty_pdf_raises`, `test_catalog_filters_build_expected_sql` (unit-test the query builder function `catalog_query(params) -> Select` by compiling SQL), `test_library_put_rejects_unknown_shelf_422`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat: PDF import, catalog filters, library shelves`.

### Task 9: Frontend — auth, settings, API client

**Files:**
- Create: `frontend/app/login/page.tsx`, `frontend/app/settings/page.tsx`, `frontend/lib/session.ts`, `frontend/lib/llmKey.ts`
- Modify: `frontend/lib/api.ts`, `frontend/components/Nav.tsx`, `frontend/app/layout.tsx`
- Delete: `frontend/components/TokenGate.tsx`, `frontend/lib/auth.ts`

**Interfaces:**
- `session.ts`: `getSession(): {token, user} | null`, `setSession(...)`, `clearSession()`; storage key `beyonder.session`.
- `llmKey.ts`: `getLlmConfig(): {provider, key, model?} | null`, `setLlmConfig`, `clearLlmConfig`; storage key `beyonder.llm`; all access wrapped in try/catch.
- `api.ts`: `req()` adds `Authorization: Bearer` when signed in and `X-LLM-Provider/Key/Model` **only** on AI routes (`/translate*`, `/ask`); maps 402 → `KeyRequiredError`, 401 → clears session.
- Settings page: provider select (gemini, openrouter, groq, deepseek, openai), key input (password type), optional model, "Get a free Gemini key" guide linking https://aistudio.google.com/apikey, note that the key stays in this browser. Login page has sign-in and "have an invite?" sign-up.

- [ ] **Step 1: Implement.** **Step 2: Verify** with `docker compose --profile build up --build frontend-build` if Docker is available (expect exit 0 and `frontend/out/login/index.html`); otherwise record "not verified: Docker unavailable" in the commit body. **Step 3: Commit** `feat(web): accounts and bring-your-own-key settings`.

### Task 10: Frontend — catalog and novel page

**Files:** Modify `frontend/app/page.tsx` (catalog: search box, tag/status/length filters, sort, paged grid with `BookCover`), `frontend/app/novel/page.tsx` (metadata, chapter list with translated markers, Continue reading, shelf select, glossary + flags tabs), `frontend/lib/api.ts` (catalog params, library calls). Filters live in the URL query string.

- [ ] **Step 1: Implement. Step 2: Verify** via Docker build as Task 9. **Step 3: Commit** `feat(web): catalog and novel page`.

### Task 11: Frontend — library and reader

**Files:** Create `frontend/app/library/page.tsx`, `frontend/lib/readerPrefs.ts`, `frontend/components/ReaderSettings.tsx`, `frontend/components/GlossaryText.tsx`. Modify `frontend/app/reader/page.tsx`, `frontend/app/globals.css` (light/sepia/dark tokens).

**Interfaces:** `readerPrefs.ts`: `ReaderPrefs {font: "serif"|"sans", size: 14..26, lineHeight: 1.4..2.2, width: 560..960, theme: "light"|"sepia"|"dark"}`, `loadPrefs()`, `savePrefs()`, key `beyonder.reader`. `GlossaryText({text, terms})` wraps glossary target terms in `<abbr title="source · kind">`. Reader: prev/next, keyboard ←/→, "Translate this chapter" when signed in + untranslated (uses existing resumable step loop; shows `KeyRequiredError` as a link to Settings), "Ask about the story" panel (signed in only), flag markers.

- [ ] **Step 1: Implement. Step 2: Verify** via Docker build. **Step 3: Commit** `feat(web): library shelves and reader settings`.

### Task 12: macOS tooling and docs

**Files:** Create `Makefile` (targets `up migrate backend frontend frontend-build test admin reembed down doctor`, mirroring `run.ps1`). Modify `README.md` (stack table: model names from config, local embeddings, accounts, BYOK, free-key guide, Makefile quick start alongside PowerShell), `docs/architecture.md` (new pipeline diagram without retry loop, auth, BYOK), `docs/deploy.md` (remove `API_TOKEN`, add `ADMIN_EMAIL`/`ADMIN_PASSWORD`, `create_admin`, reembed step), `.env.example`, `render.yaml` env keys.

- [ ] **Step 1: Implement. Step 2: Verify** `make -n up migrate backend test` prints the expected commands and `make test` passes. **Step 3: Commit** `docs: macOS Makefile and v2 docs`.
