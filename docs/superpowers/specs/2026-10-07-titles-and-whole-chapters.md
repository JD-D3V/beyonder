# Translated titles and whole chapters — contract

Date: 2026-10-07 · Branch: `redo/wtr-style`

## 1. One chapter, one page (backend: `app/ingest/splitter.py`)

- Header-detected chapters are never split by length unless the section exceeds
  `_BOOK_SIZED_CHARS = 60_000` (the stray-header-holds-a-whole-book case).
- Text with no headers at all is still split by length (`_FALLBACK_CHARS`), unchanged.
- `python -m app.scripts.merge_parts [--novel ID] [--dry-run]` and `make merge-parts`:
  for each novel, finds runs of consecutive chapters whose titles are `T`, `T (2)`, `T (3)`, …
  (exactly the `_part_title` format) and merges each run into the first chapter:
  source texts joined with `\n\n`; `char_count` recomputed; the following chapters deleted and
  later chapters re-indexed so `idx` stays contiguous (0..n-1). Translations: if every part has a
  complete translation (`pieces_done IS NULL`, non-empty) in a language, join them with `\n\n`
  into the merged chapter's translation; otherwise delete that language's translation for the merged
  chapter (it becomes untranslated). Reading progress, review flags (`chapter_idx`) and
  glossary `first_chapter` values pointing at later chapters are shifted to the new indices
  (indices inside a merged run map to the run's first index). Qdrant vectors for the novel are
  rebuilt (`embed_chapters`). One transaction per novel. `--dry-run` prints the plan only.

## 2. Translated titles

Storage (migration `20261007_0009_translated_titles.py`, down_revision `20261007_0008`):
- `translations.title: str | None` (String 512) — translated chapter title for that language.
- `novels.title_en: str | None` (String 512).

Pipeline:
- When a chapter is translated (single-pass graph `node_translate`/persist, and resumable
  `translate_step` on its first call when `pieces_done` is 0), its source title (if any) is
  translated with the same glossary in one short LLM call: `translate_title(client, title, glossary) -> str`
  in `app/agents/translator.py` (plain text, one line, no quotes; keep chapter numbering
  like "Chapter 1:" — e.g. `第一章 青云山下` → `Chapter 1: Below Azure Cloud Mountain`).
  Stored in `translations.title`. Title failure with a non-LLMError → log and leave null;
  LLMError propagates like other agent calls.
- When chapter idx 0 is translated and `novels.title_en` is empty, also translate the novel title
  and store it in `novels.title_en`.

API (all additive; existing fields unchanged):
- `NovelOut.title_en: str | None`.
- `ChapterOut` (rows from `GET /novels/{id}/chapters`): `title_en: str | None` (from the `en` translation).
- `ChapterDetail` (`GET /novels/{id}/chapters/{idx}`): `title_en: str | None`.
- `TranslateResult` and `TranslateStepResult`: `title_en: str | None`.
- `PATCH /novels/{id}` (admin) accepts optional `title_en`.
- New `POST /novels/{id}/titles/translate` (admin, uses `resolve_llm` like translate routes) →
  `{"chapters": int, "novel": bool}`: translates titles for chapters that have a complete `en`
  translation but `title IS NULL`, plus the novel title if `title_en` is empty. Batches titles
  (up to 40 per LLM call, JSON list in/out) to save quota.

Frontend:
- Display rule everywhere: show `title_en` when present, else the source title; when both exist,
  put the source title in a `title` attribute (hover) — reader heading, chapter list on the novel
  page, catalog cards, library, novel page header, breadcrumbs.
- Novel page: admin-only button "Translate titles" (icon IconLanguages) calling the new route;
  shows result count; handles KeyRequiredError like translate.
- Edit details form: `title_en` field.
- Reader: after a translate/step response with `title_en`, update the heading without reload.
