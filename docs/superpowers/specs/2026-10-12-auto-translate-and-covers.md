# Auto Google translation on add, Gemini optional, automatic covers — contract

Date: 2026-10-12 · Branch: `redo/wtr-style`. Decision: server-side machine translation uses Google's
free web endpoint (user's choice, aware it is unofficial and can be rate-limited/blocked), behind a
provider switch so it can be changed to LibreTranslate or the official API later.

## Backend
- `app/mt/` package: `provider.py` interface `async translate(texts: list[str], source="zh-CN", target="en") -> list[str]`;
  `google_free.py` (GET `https://translate.googleapis.com/translate_a/single?client=gtx&sl=..&tl=..&dt=t&q=..`,
  chunks ≤ 4500 chars on paragraph boundaries, joins the `[0][*][0]` segments); `libre.py` (existing
  LIBRETRANSLATE_URL proxy logic moved here). `MT_PROVIDER=google_free|libretranslate|off` (default google_free).
  Process-wide limiter: `MT_RPS` (default 1 request/s), exponential backoff on 429/5xx (max 5 tries), circuit
  breaker: after 3 consecutive blocks pause all MT for 15 min and log loudly. Web+ glossary pre-substitution
  (source term → English target, longest first, `first_chapter <= chapter`) before sending.
- Translations get an engine: migration `20261012_0018_translation_engine` (down_revision `20261012_0017`):
  `translations.engine` ('ai'|'mt', existing rows 'ai'), unique becomes (chapter_id, target_lang, engine);
  `novels.author_en`, `novels.description_en`. All existing AI code paths write engine='ai'.
- Chapter detail adds `translation_mt: str|None`, `title_mt: str|None`; existing `translation`/`title_en` stay
  AI-only. Chapter list rows add `mt: bool` (machine translation exists) and `title_en` falls back to the MT
  title when no AI title exists. NovelOut adds `author_en`, `description_en`; `title_en` filled by MT if empty.
  `translated_count` counts chapters with either engine; add `ai_translated_count`.
- Auto-translate on add: every new public or private novel (upload, URL, TOC import, seed) enqueues an
  `mt` job (reuse `import_jobs` with `kind='mt'` column added in the same migration, or a sibling table —
  implementer's choice, documented) that translates novel title, author, description, then chapter titles
  and chapter texts in order (chapter 0 first). Startup/periodic sweep enqueues books with untranslated
  chapters. Admin `POST /novels/{id}/mt` re-runs; `GET /novels/{id}/mt` → `{status, done, total}` (visible to
  whoever can see the book). Private books are translated too (owner's book, no key needed).
- Covers on add: URL/TOC imports take `og:image` / `twitter:image` / first large `<img>` in the book's
  index or first page (same SSRF-guarded fetch, existing cover pipeline); seed classics use Wikidata
  (entity search by original title, P18 image → `https://commons.wikimedia.org/wiki/Special:FilePath/<file>?width=600`).
  Never fails an import. `python -m app.scripts.fill_covers` backfills books without covers.

## Frontend
- Titles/authors everywhere show English by default (`title_en`/`author_en`), with the original in a muted
  line ("原名 / Original: 西游记 · 吴承恩") on the novel page header and reader breadcrumb, and as hover text
  on cards. Description shows `description_en` with a "Show original" toggle.
- Reader view switch: **Google** (default) / **Gemini** / **Source** / **Both**. Google shows `translation_mt`;
  if it's not ready yet, fall back to the existing browser Web translation with a note "Machine translation
  in progress (n/total)". Gemini shows the AI translation, or the existing "Translate with Gemini" button.
  Remember the last choice per browser. Chapter list marks G (machine) / AI.
