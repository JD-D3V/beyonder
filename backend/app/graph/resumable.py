"""Resumable, time-boxed chapter translation.

The single-pass graph (``run_translation_graph``) does extract -> translate ->
critic-retry -> relations in one request. For a long chapter that is too much
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

It intentionally skips the whole-chapter critic retry-loop: that step
re-translates the entire chapter on a nitpick and cannot be resumed. Callers
route short chapters to ``/translate`` (with the critic) and long ones here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..agents.relation import extract_relations_from_chapter
from ..agents.translator import split_paragraphs, translate_paragraph
from ..common.logging import get_logger
from ..embed.gemini import get_gemini
from ..storage.db import get_session
from ..storage.repository import (
    get_chapter_by_idx,
    get_novel,
    get_terms_for_chapters,
    get_translation,
    insert_relations,
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
    # A piece came back empty this call (model returned nothing, almost always a
    # transient rate-limit/outage after its retries). No progress was made and
    # nothing was corrupted; the caller should pause and retry the same piece.
    stalled: bool = False


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
    novel_id: int,
    chapter_idx: int,
    target_lang: str = "en",
    time_budget_s: float = STEP_BUDGET_S,
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
    gm = get_gemini()

    # Empty chapter: record a complete empty translation so the UI stops asking.
    if total == 0:
        with get_session() as s:
            upsert_translation(
                s, chapter_id=chap_id, target_lang=target_lang, text="",
                model=gm.model_name, critic_passes=0, pieces_done=None,
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

    done = start
    t0 = time.monotonic()
    for i in range(start, total):
        r = await translate_paragraph(
            pieces[i],
            glossary=glossary,
            target_lang=target_lang,
            chapter_idx=chapter_idx,
            client=gm,
        )
        if pieces[i].strip() and not r.translation.strip():
            # generate() already retried this piece and still got nothing back —
            # a transient rate-limit or model outage. Do NOT save or advance:
            # completing now would bake a gap into the chapter permanently.
            # Stop; the next call retries this same piece after the caller pauses.
            log.warning(
                "translate_step.piece_empty",
                novel_id=novel_id,
                chapter_idx=chapter_idx,
                piece=i,
            )
            return StepResult(
                chapter_idx, done, total, complete=False, stalled=True
            )
        acc = (acc + "\n\n" + r.translation) if acc else r.translation
        for t in r.new_terms:
            pair = (t["source_term"], t["target_term"])
            if pair not in glossary:
                glossary.append(pair)
        done = i + 1
        with get_session() as s:
            if r.new_terms:
                upsert_terms(
                    s, novel_id=novel_id, entries=r.new_terms, target_lang=target_lang
                )
            upsert_translation(
                s, chapter_id=chap_id, target_lang=target_lang, text=acc,
                model=gm.model_name, critic_passes=0,
                pieces_done=(None if done == total else done),
            )
        if done < total and (time.monotonic() - t0) >= time_budget_s:
            break

    complete = done == total
    if complete:
        # Relations once. Best-effort: the translation is already saved above,
        # so a failure here must not fail the step or lose the translation.
        try:
            entities = [src for src, _ in glossary]
            rels = await extract_relations_from_chapter(
                novel_title=novel_title,
                chapter_idx=chapter_idx,
                chapter_text=source,
                entities=entities,
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
    return StepResult(chapter_idx, done, total, complete)
