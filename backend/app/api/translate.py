"""Translation routes. Every call runs on the caller's own LLM key (BYOK)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.deps import current_user
from ..common.logging import get_logger
from ..graph.orchestrator import run_translation_graph
from ..graph.resumable import translate_step
from ..llm.client import LLMError
from ..llm.resolve import resolve_llm
from ..storage.db import get_session
from ..storage.models import User
from ..storage.repository import (
    chapter_rows,
    get_chapter_by_idx,
    get_novel,
    get_translation,
    reset_translation,
)
from .schemas import (
    TranslateBatchIn,
    TranslateBatchResult,
    TranslateIn,
    TranslateResult,
    TranslateStepIn,
    TranslateStepResult,
)

log = get_logger(__name__)
router = APIRouter()


def _complete_translation(s, novel_id: int, idx: int, target_lang: str):
    """(chapter, translation) where translation is set only if it is complete."""
    chap = get_chapter_by_idx(s, novel_id, idx)
    if chap is None:
        return None, None
    tr = get_translation(s, chapter_id=chap.id, target_lang=target_lang)
    if tr is not None and tr.pieces_done is None and tr.text:
        return chap, tr
    return chap, None


@router.post("/translate", response_model=TranslateResult)
async def translate(
    body: TranslateIn, request: Request, user: User = Depends(current_user)
) -> TranslateResult:
    llm = resolve_llm(request.headers, user)
    with get_session() as s:
        novel = get_novel(s, body.novel_id)
        if novel is None:
            raise HTTPException(404, "novel not found")
        title = novel.title
        src_lang = novel.source_lang
        chap, done = _complete_translation(
            s, body.novel_id, body.chapter_idx, body.target_lang
        )
        if done is not None:
            if not (user.is_admin and body.force):
                # Non-admins (and admins who did not ask) get what is saved.
                return TranslateResult(
                    chapter_idx=body.chapter_idx,
                    translation=done.text,
                    new_terms=0,
                    critic_passes=done.critic_passes,
                )
    # Forced admin runs overwrite in place: the graph's upsert replaces the row.
    state = await run_translation_graph(
        llm=llm,
        novel_id=body.novel_id,
        novel_title=title,
        source_lang=src_lang,
        target_lang=body.target_lang,
        chapter_idx=body.chapter_idx,
        translated_by=user.id,
    )
    if state.error:
        raise HTTPException(400, state.error)
    return TranslateResult(
        chapter_idx=body.chapter_idx,
        translation=state.translation,
        new_terms=len(state.new_terms),
        critic_passes=state.critic_passes,
    )


@router.post("/translate/batch", response_model=TranslateBatchResult)
async def translate_batch(
    body: TranslateBatchIn, request: Request, user: User = Depends(current_user)
) -> TranslateBatchResult:
    """Translate the next few untranslated chapters, in order.

    Deliberately a bounded synchronous call rather than a background job. The
    free instance sleeps when no request is in flight, so a detached job can be
    suspended halfway with nobody watching, and in-memory job state would not
    survive the restart. A small batch finishes inside one request, every
    chapter is saved as it completes, and the caller decides whether to ask for
    more. The free Gemini tier allows 15 requests a minute, so a batch of three
    chapters is also about as much as the rate limiter will pass without
    stalling.
    """
    llm = resolve_llm(request.headers, user)
    with get_session() as s:
        novel = get_novel(s, body.novel_id)
        if novel is None:
            raise HTTPException(404, "novel not found")
        title = novel.title
        src_lang = novel.source_lang
        pending = [
            r.idx
            for r in chapter_rows(s, body.novel_id, target_lang=body.target_lang)
            if not r.translated
        ]

    if not pending:
        return TranslateBatchResult(translated=[], remaining=0, done=True)

    batch = pending[: body.limit]
    translated: list[int] = []
    error: str | None = None

    for idx in batch:
        try:
            state = await run_translation_graph(
                llm=llm,
                novel_id=body.novel_id,
                novel_title=title,
                source_lang=src_lang,
                target_lang=body.target_lang,
                chapter_idx=idx,
                translated_by=user.id,
            )
        except LLMError:
            if not translated:
                raise  # nothing done yet: surface key/rate/upstream as HTTP
            error = f"chapter {idx + 1}: model unavailable"
            break
        except Exception as e:  # network, quota, model outage
            error = f"chapter {idx + 1}: {e}"
            break
        if state.error:
            error = f"chapter {idx + 1}: {state.error}"
            break
        translated.append(idx)

    remaining = len(pending) - len(translated)
    log.info(
        "translate.batch",
        novel_id=body.novel_id,
        done=len(translated),
        remaining=remaining,
        error=error,
    )
    return TranslateBatchResult(
        translated=translated,
        remaining=remaining,
        done=remaining == 0,
        error=error,
    )


@router.post("/translate/step", response_model=TranslateStepResult)
async def translate_step_route(
    body: TranslateStepIn, request: Request, user: User = Depends(current_user)
) -> TranslateStepResult:
    """Resumable translation for a long chapter.

    Translates as many pieces as fit a short time budget, saving each one, then
    reports progress. Call it repeatedly until ``complete`` is true. Unlike
    /translate it skips the whole-chapter critic retry-loop — that is what lets
    a chapter too big for one request finish over several short ones.

    A complete translation is final for non-admins (409 ``already_translated``).
    An admin sending ``force`` has it deleted first; the step then resumes from
    scratch, so ``force`` belongs on the first call only.
    """
    llm = resolve_llm(request.headers, user)
    with get_session() as s:
        if get_novel(s, body.novel_id) is None:
            raise HTTPException(404, "novel not found")
        chap, done = _complete_translation(
            s, body.novel_id, body.chapter_idx, body.target_lang
        )
        if done is not None:
            if not user.is_admin:
                raise HTTPException(
                    409,
                    detail={
                        "code": "already_translated",
                        "detail": "This chapter is already translated.",
                    },
                )
            if body.force:
                reset_translation(
                    s, chapter_id=chap.id, target_lang=body.target_lang
                )
    res = await translate_step(
        llm=llm,
        novel_id=body.novel_id,
        chapter_idx=body.chapter_idx,
        target_lang=body.target_lang,
        translated_by=user.id,
    )
    if res.error:
        raise HTTPException(400, res.error)
    return TranslateStepResult(
        chapter_idx=res.chapter_idx,
        pieces_done=res.pieces_done,
        pieces_total=res.pieces_total,
        complete=res.complete,
        stalled=res.stalled,
    )
