"""FastAPI routes.

Endpoints
---------
GET  /health
GET  /novels
POST /novels/ingest/text
POST /novels/ingest/url
POST /novels/embed
POST /translate
POST /ask
GET  /novels/{id}/glossary
GET  /novels/{id}/kg
POST /progress
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from ..agents.qa import answer_question
from ..common.logging import get_logger
from ..embed.pipeline import embed_chapters
from ..graph.orchestrator import run_translation_graph
from ..ingest.lang import detect_lang
from ..ingest.scraper import scrape_many
from ..ingest.splitter import split_chapters
from ..kg.graph import build_subgraph
from ..storage.db import get_session
from ..storage.models import Chapter, Novel
from ..storage.repository import (
    create_novel,
    get_chapters,
    get_novel,
    get_or_create_user,
    get_terms_for_chapters,
    insert_chapter,
    list_novels,
    set_user_chapter,
)
from .schemas import (
    AskIn,
    AskOut,
    CitationOut,
    EmbedIn,
    EmbedResult,
    GlossaryEntryOut,
    IngestResult,
    IngestTextIn,
    IngestUrlIn,
    KgEdge,
    KgNode,
    KgOut,
    NovelOut,
    ProgressIn,
    TranslateIn,
    TranslateResult,
)

log = get_logger(__name__)
router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/novels", response_model=list[NovelOut])
async def list_novels_route() -> list[NovelOut]:
    with get_session() as s:
        novels = list_novels(s)
        counts = dict(
            s.execute(
                select(Chapter.novel_id, func.count(Chapter.id)).group_by(
                    Chapter.novel_id
                )
            ).all()
        )
        return [
            NovelOut(
                id=n.id,
                title=n.title,
                source_lang=n.source_lang,
                source_url=n.source_url,
                chapter_count=int(counts.get(n.id, 0)),
            )
            for n in novels
        ]


@router.post("/novels/ingest/text", response_model=IngestResult)
async def ingest_text(body: IngestTextIn) -> IngestResult:
    text = body.text
    lang = body.source_lang or detect_lang(text)
    parsed = split_chapters(text)
    if not parsed:
        raise HTTPException(400, "no chapters parsed from text")
    with get_session() as s:
        novel = create_novel(
            s, title=body.title, source_lang=lang, source_url=body.source_url
        )
        n = 0
        for c in parsed:
            insert_chapter(
                s,
                novel_id=novel.id,
                idx=c.idx,
                title=c.title,
                source_text=c.text,
            )
            n += 1
        return IngestResult(novel_id=novel.id, chapters_added=n)


@router.post("/novels/ingest/url", response_model=IngestResult)
async def ingest_url(body: IngestUrlIn) -> IngestResult:
    pages = await scrape_many(body.urls, concurrency=2)
    combined = "\n\n".join(p.text for p in pages if p.text)
    if not combined.strip():
        raise HTTPException(400, "scrape returned empty text")
    lang = body.source_lang or detect_lang(combined)
    parsed = split_chapters(combined)
    if not parsed:
        # Fallback: one chapter per page
        parsed_pages = []
        for i, p in enumerate(pages):
            if p.text.strip():
                from ..ingest.splitter import ParsedChapter

                parsed_pages.append(
                    ParsedChapter(idx=i, title=p.title, text=p.text)
                )
        parsed = parsed_pages
    with get_session() as s:
        novel = create_novel(s, title=body.title, source_lang=lang)
        n = 0
        for c in parsed:
            insert_chapter(
                s,
                novel_id=novel.id,
                idx=c.idx,
                title=c.title,
                source_text=c.text,
            )
            n += 1
        return IngestResult(novel_id=novel.id, chapters_added=n)


@router.post("/novels/embed", response_model=EmbedResult)
async def embed(body: EmbedIn) -> EmbedResult:
    with get_session() as s:
        novel = get_novel(s, body.novel_id)
        if novel is None:
            raise HTTPException(404, "novel not found")
        chaps = get_chapters(s, body.novel_id, up_to=body.to_chapter)
        chaps = [c for c in chaps if c.idx >= body.from_chapter]
    n = await embed_chapters(body.novel_id, chaps)
    return EmbedResult(points=n)


@router.post("/translate", response_model=TranslateResult)
async def translate(body: TranslateIn) -> TranslateResult:
    with get_session() as s:
        novel = get_novel(s, body.novel_id)
        if novel is None:
            raise HTTPException(404, "novel not found")
        title = novel.title
        src_lang = novel.source_lang
    state = await run_translation_graph(
        novel_id=body.novel_id,
        novel_title=title,
        source_lang=src_lang,
        target_lang=body.target_lang,
        chapter_idx=body.chapter_idx,
    )
    if state.error:
        raise HTTPException(400, state.error)
    return TranslateResult(
        chapter_idx=body.chapter_idx,
        translation=state.translation,
        new_terms=len(state.new_terms),
        critic_passes=state.critic_passes,
    )


@router.post("/ask", response_model=AskOut)
async def ask(body: AskIn) -> AskOut:
    with get_session() as s:
        novel = get_novel(s, body.novel_id)
        if novel is None:
            raise HTTPException(404, "novel not found")
        title = novel.title
    res = await answer_question(
        question=body.question,
        novel_id=body.novel_id,
        novel_title=title,
        current_chapter=body.current_chapter,
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
async def glossary(novel_id: int, up_to: int = 100000, target_lang: str = "en"):
    with get_session() as s:
        terms = get_terms_for_chapters(
            s, novel_id, up_to_chapter=up_to, target_lang=target_lang
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
async def knowledge_graph(novel_id: int, up_to: int = 100000, target_lang: str = "en"):
    with get_session() as s:
        nodes, edges = build_subgraph(
            s, novel_id=novel_id, up_to_chapter=up_to, target_lang=target_lang
        )
        return KgOut(
            nodes=[KgNode(**n.__dict__) for n in nodes],
            edges=[KgEdge(**e.__dict__) for e in edges],
        )


@router.post("/progress")
async def progress(body: ProgressIn) -> dict:
    with get_session() as s:
        user = get_or_create_user(s, body.handle)
        set_user_chapter(s, user, body.novel_id, body.current_chapter)
    return {"ok": True}


_EVAL_LATEST = Path(__file__).resolve().parents[2] / "eval" / "reports" / "latest.json"


@router.get("/eval/latest")
async def eval_latest() -> dict:
    """Serve the most recent eval run for the dashboard.

    Returns 404 with a hint if no report exists yet.
    """
    if not _EVAL_LATEST.exists():
        raise HTTPException(
            404, "no eval report yet — run: python -m eval.run all"
        )
    try:
        return json.loads(_EVAL_LATEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"corrupt eval report: {e}") from e
