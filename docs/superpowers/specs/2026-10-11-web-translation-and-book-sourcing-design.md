# Free web translation and book sourcing — design

Date: 2026-10-11 · Branch: `redo/wtr-style`

## Goals
1. Readers can read any chapter for free, without an AI key, like WTR-LAB's "Web" / "Web+" modes.
2. The catalog has books from day one, and adding books is easy — without republishing copyrighted
   novels scraped from pirate sites.

## Decisions (agreed in chat)
- Free translation: browser on-device translation first (Chrome Translator API), self-hosted
  LibreTranslate as an optional fallback. No unofficial Google endpoint (against Google's terms).
- Books: (a) public-domain classics seed + private per-user imports + admin-published bulk import.

## 1. Web translation ("Web" mode)
- `frontend/lib/webTranslate.ts`:
  `webTranslateAvailable(): Promise<"browser"|"server"|null>` and
  `webTranslate(paragraphs: string[], glossary: GlossaryEntry[], onProgress?): Promise<string[]>`.
  - "browser": `globalThis.Translator` (Chrome built-in): `availability({sourceLanguage:"zh",targetLanguage:"en"})`;
    `create(...)` (may download a language pack — show progress via `monitor`); translate paragraph by paragraph.
  - "server": `GET /mt/status` → `{available: bool}`; `POST /mt/translate {texts: string[]}` → `{texts: string[]}`.
  - Web+ glossary step: before MT, replace each glossary source term in the Chinese text with its English
    target (longest first, only terms with `first_chapter <= chapter`); MT leaves embedded English names intact.
  - Cache results in IndexedDB keyed `novel:idx:sha1(source)`, wrapped in try/catch (works without it).
- Reader view switch becomes **AI / Web / Source / Both** (Both = source + whichever translation is shown).
  When a chapter has no AI translation, the reader opens in Web mode if available; otherwise it shows
  "Free translation needs desktop Chrome — or translate with AI". Chapter titles are web-translated too.
  Web output is never saved to the server and never counts as "translated".
- Backend `app/api/mt.py`: `/mt/status`, `/mt/translate` proxy to `LIBRETRANSLATE_URL` (unset → available
  false, 404 on translate). Public, rate-limited 60 requests / 5 min per client IP, max 20 texts and
  10,000 characters per request; 502 on upstream failure.
- `docker-compose.yml`: optional `libretranslate` service under profile `mt`
  (`LT_LOAD_ONLY=zh,en`), port 5000. Docs note ~2 GB RAM.

## 2. Private books
- `novels.visibility` (`public` | `private`, default `public`) and `novels.owner_id` (FK users, SET NULL).
  Migration `20261011_0015_visibility` (down_revision `20261009_0014`).
- Imports by non-admins are `private`, owned by the importer. Admin imports default `public`; admin can
  publish/unpublish (`PATCH /novels/{id}` `visibility`).
- One helper `visible_novel_or_404(session, novel_id, user)` used by EVERY route that takes a novel id
  (novel, chapters, glossary, kg, flags, ask, translate*, reviews/rating/comments, cover, progress,
  library, check-updates, titles). Private books: owner and admin only; others get 404 (not 403).
- Catalog `GET /novels`: public books; signed-in users also see their own private books
  (`mine=true` filter shows only those). Rankings, view counting, reviews and comments: public books only.
- Frontend: "Private" badge; import page asks Private/Public (Public only for admin); novel page admin
  control Publish/Unpublish; catalog "My imports" filter when signed in.

## 3. Bulk table-of-contents import
- `POST /novels/ingest/toc {index_url, title?, max_chapters (1..500, default 200), visibility}` (signed in)
  → 202 `{job_id}`. Discovers chapter links on the TOC page (same host, page order; reuse
  `app/ingest/updates.py` discovery rules), creates the novel, then scrapes chapters in the background
  (asyncio task, 1 request/second, SSRF guard on every fetch), one chapter per page with `source_url`,
  sets `source_index_url`, embeds at the end.
- `import_jobs` table (id, user_id, novel_id, status queued|running|done|failed, total, done, error,
  created_at, updated_at); migration `20261011_0016_import_jobs` (down_revision `…_0015`).
  `GET /imports/{id}` (owner/admin) and `GET /imports?mine=true`. At most 2 running jobs per user;
  jobs left `running` at startup are marked `failed` ("server restarted").
- Scheduled updates: `AUTO_UPDATE_HOURS` (default 0 = off); when > 0 an in-process loop runs the
  existing update check for public books with a `source_index_url` every N hours. `make check-updates`
  stays for system cron.
- Frontend import page: "Table of contents URL" mode with progress bar polling the job.

## 4. Public-domain seed
- `python -m app.scripts.seed_classics [--works xiyouji,fengshen,...] [--max-chapters 30]` and
  `make seed-classics`. Fetches from zh.wikisource.org via the MediaWiki API (descriptive User-Agent,
  1 request/second), creates public, completed novels with author, description, tags and
  `source_url` attribution "Source: Wikisource (public domain)". Works: 西游记, 封神演义, 三国演义,
  水浒传, 聊斋志异, 红楼梦. Idempotent (skips existing titles). Embeds chapters.

## Testing
Backend unit + `@pytest.mark.db` tests (visibility matrix on every novel-id route is the key test),
mocked HTTP for TOC import, MT proxy and Wikisource. Frontend verified by the Docker production build.
