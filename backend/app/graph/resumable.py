"""Resumable, time-boxed chapter translation.

The single-pass graph (``run_translation_graph``) does extract -> translate ->
deterministic QA -> relations in one request. For a long chapter that is too much
work for one HTTP request on a small instance: it times out and nothing is
saved.

``translate_step`` does the same piece splitting the translator already does
(``split_paragraphs``, ~1200 chars each, one model call per piece) but:

  * resumes from the last saved piece (``translations.pieces_done``),
  * saves after every piece, so a dropped connection never loses work,
  * stops once a wall-clock budget is spent and reports progress, so no single
    request runs long,
  * runs relations once when the final piece lands (best-effort — the
    translation is already saved by then).

It never calls the LLM critic; on completion it runs only the deterministic
checks (glossary drift fix, leftover CJK) and stores review flags. Callers
route short chapters to ``/translate`` (with the critic) and long ones here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import select

from ..agents.relation import extract_relations_from_chapter
from ..agents.translator import split_paragraphs, translate_paragraph, translate_title
from ..common.logging import get_logger
from ..glossary.seed import match_seed
from ..review.checks import deterministic_flags
from ..llm.client import LLMClient
from ..storage.db import get_session
from ..storage.models import Translation
from ..storage.repository import (
    get_chapter_by_idx,
    get_novel,
    get_terms_for_chapters,
    get_translation,
    insert_relations,
    insert_seed_terms,
    load_variants,
    replace_open_flags,
    term_dicts,
    update_novel,
    upsert_terms,
    upsert_translation,
)

log = get_logger(__name__)

# Wall-clock budget per request. The check runs after each piece, so at least
# one piece always completes; a request is roughly this long plus one piece.
STEP_BUDGET_S = 25.0


@dataclass
class StepResult:
    chapter_idx: int
    pieces_done: int
    pieces_total: int
    complete: bool
    error: str | None = None
    # A piece came back blank or garbled this call without an LLMError (key,
    # rate-limit and outage errors raise instead). No progress was made and
    # nothing was corrupted; the caller should pause and retry the same piece.
    stalled: bool = False
    # Terms persisted this call (seed hits, plus any the model found per piece).
    new_terms: list[dict] = field(default_factory=list)
    # Translated chapter title, set on the call that translated it.
    title_en: str | None = None


def _dedup_by_id(rows: list[dict]) -> list[dict]:
    seen: set[int] = set()
    out = []
    for r in rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


def plan_resume(
    *,
    existing_done: int | None,
    existing_text: str,
    total: int,
    already_complete: bool,
) -> tuple[int, str, bool]:
    """Decide where a resumable run picks up, from the saved row and piece count.

    Returns ``(start_piece, accumulated_prefix, short_circuit_complete)``:
      * already complete -> stop, don't re-translate;
      * no saved progress -> start at 0 with an empty prefix;
      * partway -> resume at ``pieces_done`` with the saved text as the prefix;
      * a marker left past the end (source got shorter on re-import) -> start over.
    """
    if already_complete:
        return total, existing_text, True
    start = existing_done if existing_done is not None else 0
    if start > total:
        return 0, "", False
    acc = existing_text if start > 0 else ""
    return start, acc, False


async def translate_step(
    *,
    llm: LLMClient,
    novel_id: int,
    chapter_idx: int,
    target_lang: str = "en",
    time_budget_s: float = STEP_BUDGET_S,
    translated_by: int | None = None,
) -> StepResult:
    # --- load current state in one short session -------------------------
    with get_session() as s:
        chap = get_chapter_by_idx(s, novel_id, chapter_idx)
        if chap is None:
            return StepResult(chapter_idx, 0, 0, False, error="chapter not found")
        source = chap.source_text
        chap_id = chap.id
        novel = get_novel(s, novel_id)
        novel_title = novel.title if novel else ""
        need_novel_title = (
            chapter_idx == 0 and novel is not None and not novel.title_en
        )
        chapter_title = getattr(chap, "title", None)
        tr = get_translation(s, chapter_id=chap_id, target_lang=target_lang)
        existing_text = tr.text if tr else ""
        existing_done = tr.pieces_done if tr else None
        already_complete = tr is not None and tr.pieces_done is None and bool(tr.text)
        glossary = [
            (t.source_term, t.target_term)
            for t in get_terms_for_chapters(
                s, novel_id, up_to_chapter=chapter_idx, target_lang=target_lang
            )
        ]

    pieces = split_paragraphs(source)
    total = len(pieces)

    # Empty chapter: record a complete empty translation so the UI stops asking.
    if total == 0:
        with get_session() as s:
            upsert_translation(
                s, chapter_id=chap_id, target_lang=target_lang, text="",
                model=llm.model_name, critic_passes=0, pieces_done=None,
                translated_by=translated_by, allow_empty=True,
            )
        return StepResult(chapter_idx, 0, 0, True)

    start, acc, complete_already = plan_resume(
        existing_done=existing_done,
        existing_text=existing_text,
        total=total,
        already_complete=already_complete,
    )
    # A complete translation already exists — the resumable path never
    # re-translates (that is the "can't re-translate a long chapter" contract).
    if complete_already:
        return StepResult(chapter_idx, total, total, True)

    new_terms: list[dict] = []
    if start == 0:
        # Seed the glossary once per chapter, before the first piece, so long
        # chapters get the same built-in terms as the single-pass path.
        hits = match_seed(source, {src for src, _ in glossary})
        if hits:
            for h in hits:
                h["first_chapter"] = chapter_idx
                h["added_by"] = translated_by
            with get_session() as s:
                new_terms.extend(
                    term_dicts(
                        insert_seed_terms(
                            s, novel_id=novel_id, entries=hits,
                            target_lang=target_lang,
                        )
                    )
                )
            glossary.extend((h["source_term"], h["target_term"]) for h in hits)

    # Titles once per chapter, on the first call, with the glossary as it
    # stands (seed hits included). LLMError propagates; other failures leave
    # the title unset.
    title_en: str | None = None
    novel_title_en: str | None = None
    if start == 0:
        if chapter_title and chapter_title.strip():
            title_en = await translate_title(llm, chapter_title, glossary) or None
        if need_novel_title and novel_title.strip():
            novel_title_en = await translate_title(llm, novel_title, glossary) or None

    done = start
    t0 = time.monotonic()
    for i in range(start, total):
        # LLMError (bad key, rate limit, outage) propagates: the route maps it
        # to 400/429/502 instead of reporting a misleading stall.
        r = await translate_paragraph(
            pieces[i],
            glossary=glossary,
            target_lang=target_lang,
            chapter_idx=chapter_idx,
            client=llm,
        )
        if pieces[i].strip() and not r.translation.strip():
            # A non-error but blank/garbled reply (errors raise above). Do NOT
            # save or advance: completing now would bake a gap into the chapter
            # permanently.
            # Stop; the next call retries this same piece after the caller pauses.
            log.warning(
                "translate_step.piece_empty",
                novel_id=novel_id,
                chapter_idx=chapter_idx,
                piece=i,
            )
            return StepResult(
                chapter_idx, done, total, complete=False, stalled=True,
                new_terms=_dedup_by_id(new_terms),
            )
        acc = (acc + "\n\n" + r.translation) if acc else r.translation
        for t in r.new_terms:
            pair = (t["source_term"], t["target_term"])
            if pair not in glossary:
                glossary.append(pair)
        done = i + 1
        with get_session() as s:
            if r.new_terms:
                for t in r.new_terms:
                    t.setdefault("added_by", translated_by)
                made: list = []
                upsert_terms(
                    s, novel_id=novel_id, entries=r.new_terms,
                    target_lang=target_lang, created_out=made,
                )
                new_terms.extend(term_dicts(made))
            wrote = upsert_translation(
                s, chapter_id=chap_id, target_lang=target_lang, text=acc,
                model=llm.model_name, critic_passes=0,
                pieces_done=(None if done == total else done),
                translated_by=translated_by,
                title=title_en,
            )
            if wrote and novel_title_en:
                nv = get_novel(s, novel_id)
                if nv is not None and not nv.title_en:
                    update_novel(s, novel_id, title_en=novel_title_en)
                novel_title_en = None
        if wrote is False:
            # A complete translation landed meanwhile (another request); our
            # write was refused so it is not clobbered. Nothing more to do.
            return StepResult(
                chapter_idx, total, total, True, new_terms=_dedup_by_id(new_terms)
            )
        if done < total and (time.monotonic() - t0) >= time_budget_s:
            break

    complete = done == total
    if complete:
        # Deterministic QA on the finished text. Best-effort, like relations.
        try:
            with get_session() as s:
                variants = load_variants(s, novel_id)
                fixed, qa_flags = deterministic_flags(source, acc, glossary, variants)
                # Lock the row and only act if it is still the text QA ran on.
                row = s.execute(
                    select(Translation)
                    .where(
                        Translation.chapter_id == chap_id,
                        Translation.target_lang == target_lang,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if row is not None and row.text == acc and row.pieces_done is None:
                    if fixed != acc:
                        row.text = fixed
                    replace_open_flags(s, novel_id, chapter_idx, qa_flags)
        except Exception as e:  # noqa: BLE001 - QA flags are optional
            log.warning(
                "translate_step.qa_failed", chapter_idx=chapter_idx, err=str(e)
            )
        # Relations once. Best-effort: the translation is already saved above,
        # so a failure here must not fail the step or lose the translation.
        try:
            entities = [src for src, _ in glossary]
            rels = await extract_relations_from_chapter(
                novel_title=novel_title,
                chapter_idx=chapter_idx,
                chapter_text=source,
                entities=entities,
                client=llm,
            )
            if rels:
                with get_session() as s:
                    insert_relations(s, novel_id=novel_id, entries=rels)
        except Exception as e:  # noqa: BLE001 - relations are optional
            log.warning(
                "translate_step.relations_failed", chapter_idx=chapter_idx, err=str(e)
            )

    log.info(
        "translate_step",
        novel_id=novel_id,
        chapter_idx=chapter_idx,
        done=done,
        total=total,
        complete=complete,
    )
    return StepResult(
        chapter_idx, done, total, complete, new_terms=_dedup_by_id(new_terms),
        title_en=title_en,
    )
