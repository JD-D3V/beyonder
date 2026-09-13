"""FastAPI routes.

Endpoints
---------
GET    /health
GET    /novels
GET    /novels/{id}
PATCH  /novels/{id}
DELETE /novels/{id}
GET    /novels/{id}/chapters
GET    /novels/{id}/chapters/{idx}
POST   /novels/ingest/text
POST   /novels/ingest/url
POST   /novels/upload
POST   /novels/embed
POST   /translate/batch
GET    /progress
POST /translate
POST /ask
GET  /novels/{id}/glossary
GET  /novels/{id}/kg
POST /progress
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select

from ..agents.qa import answer_question
from ..common.config import settings
from ..common.logging import get_logger
from ..embed.pipeline import embed_chapters
from ..graph.orchestrator import run_translation_graph
from ..graph.resumable import translate_step
from ..ingest.epub_loader import load_epub
from ..ingest.lang import detect_lang
from ..ingest.scraper import scrape_many
from ..ingest.splitter import split_chapters
from ..ingest.txt_loader import load_txt
from ..kg.graph import build_subgraph
from ..storage.db import get_session
from ..storage.models import Chapter, Novel
from ..storage.repository import (
    chapter_rows,
    create_novel,
    delete_novel,
    get_chapter_by_idx,
    get_chapters,
    get_novel,
    get_or_create_user,
    get_user_chapter,
    get_terms_for_chapters,
    get_translation,
    insert_chapter,
    library_rows,
    set_user_chapter,
    update_novel,
)
from .schemas import (
    AskIn,
    AskOut,
    ChapterDetail,
    ChapterOut,
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
    NovelPatch,
    ProgressOut,
    ProgressIn,
    TranslateBatchIn,
    TranslateBatchResult,
    TranslateIn,
    TranslateResult,
    TranslateStepIn,
    TranslateStepResult,
)

log = get_logger(__name__)
router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness, plus enough to tell which build and config are actually live.

    Render injects RENDER_GIT_COMMIT, so a stale deploy is visible from here
    instead of guessing at the dashboard. No secrets: model names only.
    """
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    return {
        "ok": True,
        "commit": commit[:7] if commit else "dev",
        "model": settings.gemini_model,
        "embed_model": settings.gemini_embed_model,
    }


def _split_tags(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _join_tags(tags: list[str] | None) -> str | None:
    if tags is None:
        return None
    cleaned = [t.strip().lower() for t in tags if t and t.strip()]
    # De-duplicate but keep the order the user typed.
    seen: dict[str, None] = {}
    for t in cleaned:
        seen.setdefault(t, None)
    return ", ".join(seen) or None


def _novel_out(
    novel: Novel, chapters: int, chars: int, translated: int
) -> NovelOut:
    return NovelOut(
        id=novel.id,
        title=novel.title,
        author=novel.author,
        description=novel.description,
        tags=_split_tags(novel.tags),
        status=novel.status,
        source_lang=novel.source_lang,
        source_url=novel.source_url,
        chapter_count=chapters,
        char_count=chars,
        translated_count=translated,
        updated_at=novel.updated_at.isoformat() if novel.updated_at else None,
    )


@router.get("/novels", response_model=list[NovelOut])
async def list_novels_route() -> list[NovelOut]:
    """The whole shelf, newest activity first."""
    with get_session() as s:
        return [
            _novel_out(r.novel, r.chapter_count, r.char_count, r.translated_count)
            for r in library_rows(s)
        ]


@router.get("/novels/{novel_id}", response_model=NovelOut)
async def get_novel_route(novel_id: int) -> NovelOut:
    with get_session() as s:
        for r in library_rows(s):
            if r.novel.id == novel_id:
                return _novel_out(
                    r.novel, r.chapter_count, r.char_count, r.translated_count
                )
    raise HTTPException(404, "novel not found")


@router.patch("/novels/{novel_id}", response_model=NovelOut)
async def patch_novel_route(novel_id: int, body: NovelPatch) -> NovelOut:
    with get_session() as s:
        updated = update_novel(
            s,
            novel_id,
            title=body.title,
            author=body.author,
            description=body.description,
            tags=_join_tags(body.tags),
            status=body.status,
            source_lang=body.source_lang,
        )
        if updated is None:
            raise HTTPException(404, "novel not found")
    return await get_novel_route(novel_id)


@router.delete("/novels/{novel_id}")
async def delete_novel_route(novel_id: int) -> dict:
    """Remove a book and everything derived from it."""
    with get_session() as s:
        if not delete_novel(s, novel_id):
            raise HTTPException(404, "novel not found")
    log.info("novel.deleted", novel_id=novel_id)
    return {"ok": True, "deleted": novel_id}


@router.get("/novels/{novel_id}/chapters", response_model=list[ChapterOut])
async def list_chapters_route(
    novel_id: int, target_lang: str = "en"
) -> list[ChapterOut]:
    with get_session() as s:
        if get_novel(s, novel_id) is None:
            raise HTTPException(404, "novel not found")
        return [
            ChapterOut(
                idx=r.idx,
                title=r.title,
                char_count=r.char_count,
                translated=r.translated,
                pieces_done=r.pieces_done,
            )
            for r in chapter_rows(s, novel_id, target_lang=target_lang)
        ]


@router.get("/novels/{novel_id}/chapters/{idx}", response_model=ChapterDetail)
async def get_chapter_route(
    novel_id: int, idx: int, target_lang: str = "en"
) -> ChapterDetail:
    """Read a chapter. Returns the saved translation; never calls the model."""
    with get_session() as s:
        chap = get_chapter_by_idx(s, novel_id, idx)
        if chap is None:
            raise HTTPException(404, "chapter not found")
        tr = get_translation(s, chapter_id=chap.id, target_lang=target_lang)
        return ChapterDetail(
            idx=chap.idx,
            title=chap.title,
            char_count=chap.char_count,
            source_text=chap.source_text,
            translation=tr.text if tr else None,
            translated_with=tr.model if tr else None,
            critic_passes=tr.critic_passes if tr else None,
            complete=tr is not None and tr.pieces_done is None,
            pieces_done=tr.pieces_done if tr else None,
        )


# Uploads are held in memory before parsing, so cap them. A 20 MB text file is
# already a very long novel; anything bigger is a mistake or an attack.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_TEXT_SUFFIXES = {".txt", ".text", ".md"}
_EPUB_SUFFIXES = {".epub"}


def _persist_novel(
    *,
    title: str,
    text: str,
    source_lang: str | None,
    source_url: str | None = None,
    author: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> IngestResult:
    """Split text into chapters and save the book. The one way in.

    Every import path (paste, file, URL) lands here so a book saved one way is
    indistinguishable from a book saved another way.
    """
    lang = source_lang or detect_lang(text)
    parsed = split_chapters(text)
    if not parsed:
        raise HTTPException(400, "no chapters parsed from text")
    with get_session() as s:
        novel = create_novel(
            s, title=title, source_lang=lang, source_url=source_url
        )
        update_novel(
            s,
            novel.id,
            author=author,
            description=description,
            tags=_join_tags(tags),
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
        log.info("novel.saved", novel_id=novel.id, chapters=n, lang=lang)
        return IngestResult(novel_id=novel.id, chapters_added=n, title=title)


@router.post("/novels/ingest/text", response_model=IngestResult)
async def ingest_text(body: IngestTextIn) -> IngestResult:
    return _persist_novel(
        title=body.title,
        text=body.text,
        source_lang=body.source_lang,
        source_url=body.source_url,
        author=body.author,
        description=body.description,
        tags=body.tags,
    )


@router.post("/novels/upload", response_model=IngestResult)
async def upload_novel(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    author: str | None = Form(default=None),
    description: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    source_lang: str | None = Form(default=None),
) -> IngestResult:
    """Import a book from a .txt, .md or .epub file and save it.

    The filename is the fallback title, so dragging in a file and pressing save
    is enough. Both loaders read from disk, so the upload is spooled to a temp
    file that is removed before the response is written.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "uploaded file is empty")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"file is larger than {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
        )

    name = Path(file.filename or "upload.txt").name
    suffix = Path(name).suffix.lower()
    if suffix not in _TEXT_SUFFIXES | _EPUB_SUFFIXES:
        raise HTTPException(
            400,
            f"unsupported file type {suffix or '(none)'}; use .txt, .md or .epub",
        )

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            text = (
                load_epub(tmp_path)
                if suffix in _EPUB_SUFFIXES
                else load_txt(tmp_path)
            )
        except Exception as e:  # malformed archive, unreadable encoding, ...
            log.warning("upload.parse_fail", name=name, err=str(e))
            raise HTTPException(400, f"could not read {name}: {e}") from e
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    if not text.strip():
        raise HTTPException(400, f"no text found in {name}")

    return _persist_novel(
        title=(title or Path(name).stem).strip()[:512],
        text=text,
        source_lang=source_lang,
        author=author,
        description=description,
        tags=[t for t in (tags or "").split(",") if t.strip()],
    )


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


@router.post("/translate/batch", response_model=TranslateBatchResult)
async def translate_batch(body: TranslateBatchIn) -> TranslateBatchResult:
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
                novel_id=body.novel_id,
                novel_title=title,
                source_lang=src_lang,
                target_lang=body.target_lang,
                chapter_idx=idx,
            )
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
async def translate_step_route(body: TranslateStepIn) -> TranslateStepResult:
    """Resumable translation for a long chapter.

    Translates as many pieces as fit a short time budget, saving each one, then
    reports progress. Call it repeatedly until ``complete`` is true. Unlike
    /translate it skips the whole-chapter critic retry-loop — that is what lets
    a chapter too big for one request finish over several short ones.
    """
    with get_session() as s:
        if get_novel(s, body.novel_id) is None:
            raise HTTPException(404, "novel not found")
    res = await translate_step(
        novel_id=body.novel_id,
        chapter_idx=body.chapter_idx,
        target_lang=body.target_lang,
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


@router.get("/progress", response_model=ProgressOut)
async def get_progress(novel_id: int, handle: str = "demo") -> ProgressOut:
    """Where this reader got to. Handles are per browser, not accounts."""
    with get_session() as s:
        user = get_or_create_user(s, handle)
        return ProgressOut(
            handle=handle,
            novel_id=novel_id,
            current_chapter=get_user_chapter(s, user, novel_id),
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
