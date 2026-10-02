"""Reader routes: per-account progress, Q&A, glossary, knowledge graph."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..agents.qa import answer_question
from ..auth.deps import current_user, current_user_optional
from ..llm.resolve import resolve_llm
from ..kg.graph import build_subgraph
from ..storage.db import get_session
from ..storage.models import User
from ..storage.repository import (
    get_novel,
    get_progress,
    get_terms_for_chapters,
    set_progress,
)
from .schemas import (
    AskIn,
    AskOut,
    CitationOut,
    GlossaryEntryOut,
    KgEdge,
    KgNode,
    KgOut,
    ProgressIn,
    ProgressOut,
)

router = APIRouter()

# Anonymous readers choose their own horizon; there is no stored position.
_ANON_UP_TO = 100000


def _up_to(s, user: User | None, novel_id: int, up_to: int | None) -> int:
    if up_to is not None:
        return up_to
    if user is not None:
        return get_progress(s, user.id, novel_id)
    return _ANON_UP_TO


@router.post("/ask", response_model=AskOut)
async def ask(
    body: AskIn, request: Request, user: User = Depends(current_user)
) -> AskOut:
    llm = resolve_llm(request.headers, user)
    with get_session() as s:
        novel = get_novel(s, body.novel_id)
        if novel is None:
            raise HTTPException(404, "novel not found")
        title = novel.title
        # The client's current_chapter is ignored: no peeking past your position.
        current = get_progress(s, user.id, body.novel_id)
    res = await answer_question(
        client=llm,
        question=body.question,
        novel_id=body.novel_id,
        novel_title=title,
        current_chapter=current,
        answer_lang=body.answer_lang,
        top_k=body.top_k,
    )
    citations = [
        CitationOut(
            chapter_idx=h.chapter_idx,
            char_start=h.char_start,
            char_end=h.char_end,
            text=h.text,
            score=h.score,
        )
        for h in res.hits
    ]
    return AskOut(answer=res.answer, citations=citations)


@router.get("/novels/{novel_id}/glossary", response_model=list[GlossaryEntryOut])
async def glossary(
    novel_id: int,
    up_to: int | None = None,
    target_lang: str = "en",
    user: User | None = Depends(current_user_optional),
):
    with get_session() as s:
        terms = get_terms_for_chapters(
            s,
            novel_id,
            up_to_chapter=_up_to(s, user, novel_id, up_to),
            target_lang=target_lang,
        )
        return [
            GlossaryEntryOut(
                source_term=t.source_term,
                target_term=t.target_term,
                kind=t.kind,
                first_chapter=t.first_chapter,
                confidence=t.confidence,
            )
            for t in terms
        ]


@router.get("/novels/{novel_id}/kg", response_model=KgOut)
async def knowledge_graph(
    novel_id: int,
    up_to: int | None = None,
    target_lang: str = "en",
    user: User | None = Depends(current_user_optional),
):
    with get_session() as s:
        nodes, edges = build_subgraph(
            s,
            novel_id=novel_id,
            up_to_chapter=_up_to(s, user, novel_id, up_to),
            target_lang=target_lang,
        )
        return KgOut(
            nodes=[KgNode(**n.__dict__) for n in nodes],
            edges=[KgEdge(**e.__dict__) for e in edges],
        )


@router.get("/progress", response_model=ProgressOut)
async def read_progress(
    novel_id: int, user: User = Depends(current_user)
) -> ProgressOut:
    with get_session() as s:
        return ProgressOut(
            novel_id=novel_id, current_chapter=get_progress(s, user.id, novel_id)
        )


@router.post("/progress")
async def progress(body: ProgressIn, user: User = Depends(current_user)) -> dict:
    """Explicit set: unlike reading a chapter, this may move the position back."""
    with get_session() as s:
        set_progress(s, user.id, body.novel_id, body.current_chapter)
    return {"ok": True}
