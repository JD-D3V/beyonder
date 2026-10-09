"""Catalog, chapter reading, ingest, and novel admin routes."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from typing import Literal

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile,
)

from ..agents.translator import translate_title, translate_titles_batch
from ..auth.deps import current_user, current_user_optional, require_admin
from ..common.logging import get_logger
from ..embed.pipeline import embed_chapters
from ..ingest.covers import CoverError, MAX_UPLOAD_BYTES as MAX_COVER_BYTES, process_cover
from ..ingest.epub_loader import load_epub_with_cover
from ..ingest.lang import detect_lang
from ..ingest.pdf_loader import load_pdf
from ..ingest.scraper import FetchTooLarge, UnsafeURL, fetch_bytes_guarded, scrape_many
from ..ingest.splitter import split_chapters
from ..ingest.updates import (
    NoChapterPattern, NovelNotFound, UpdateCheckUnavailable, check_novel_updates,
)
from ..ingest.txt_loader import load_txt
from ..llm.resolve import resolve_llm
from ..storage.db import get_session
from ..storage.models import Novel, Translation, User
from ..storage.repository import (
    CatalogParams,
    advance_progress,
    chapter_rows,
    cover_version,
    create_novel,
    delete_cover,
    delete_novel,
    get_cover,
    get_cover_updated_at,
    get_chapter_by_idx,
    get_chapters,
    get_novel,
    get_terms_for_chapters,
    get_translation,
    insert_chapter,
    library_rows,
    ranked_rows,
    set_cover,
    term_dicts,
    untitled_translations,
    update_novel,
    update_term,
)
from .viewstats import today_utc, track_chapter_view
from .schemas import (
    ChapterDetail,
    ChapterOut,
    CoverUrlIn,
    EmbedIn,
    EmbedResult,
    IngestResult,
    UpdateCheckResult,
    IngestTextIn,
    IngestUrlIn,
    GlossaryEntryOut,
    GlossaryPatch,
    NovelOut,
    NovelPatch,
    RankedNovelOut,
    TitlesTranslateResult,
)

log = get_logger(__name__)
router = APIRouter()


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
    novel: Novel, chapters: int, chars: int, translated: int, views_total: int = 0,
    rating_avg: float | None = None, rating_count: int = 0,
) -> NovelOut:
    cover_at = getattr(novel, "cover_updated_at", None)
    return NovelOut(
        id=novel.id,
        title=novel.title,
        title_en=novel.title_en,
        author=novel.author,
        description=novel.description,
        tags=_split_tags(novel.tags),
        status=novel.status,
        source_lang=novel.source_lang,
        source_url=novel.source_url,
        chapter_count=chapters,
        char_count=chars,
        translated_count=translated,
        views_total=views_total,
        updated_at=novel.updated_at.isoformat() if novel.updated_at else None,
        rating_avg=round(rating_avg, 2) if rating_avg is not None else None,
        rating_count=rating_count,
        has_cover=cover_at is not None,
        cover_version=cover_version(novel.id, cover_at) if cover_at else None,
    )


@router.get("/novels", response_model=list[NovelOut])
async def list_novels_route(
    q: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=16),
    min_chapters: int | None = Query(default=None, ge=0),
    max_chapters: int | None = Query(default=None, ge=0),
    sort: Literal["updated", "new", "chapters", "views", "rating"] = "updated",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[NovelOut]:
    """The catalog: searchable, filterable, newest activity first by default."""
    params = CatalogParams(
        q=q, tag=tag, status=status, min_chapters=min_chapters,
        max_chapters=max_chapters, sort=sort, limit=limit, offset=offset,
    )
    with get_session() as s:
        return [
            _novel_out(
                r.novel, r.chapter_count, r.char_count, r.translated_count,
                r.views_total, r.rating_avg, r.rating_count,
            )
            for r in library_rows(s, params)
        ]


@router.get("/rankings", response_model=list[RankedNovelOut])
async def rankings_route(
    period: Literal["day", "week", "month", "all"] = "week",
    limit: int = Query(default=20, ge=1, le=100),
) -> list[RankedNovelOut]:
    """Most-read novels in the window (UTC days); ties broken by id."""
    with get_session() as s:
        rows = ranked_rows(s, period, limit, today_utc())
        return [
            RankedNovelOut(
                **_novel_out(
                    r.novel, r.chapter_count, r.char_count, r.translated_count,
                    r.views_total, r.rating_avg, r.rating_count,
                ).model_dump(),
                views=views,
                rank=i,
            )
            for i, (views, r) in enumerate(rows, start=1)
        ]


@router.get("/novels/{novel_id}", response_model=NovelOut)
async def get_novel_route(novel_id: int) -> NovelOut:
    with get_session() as s:
        for r in library_rows(s):
            if r.novel.id == novel_id:
                return _novel_out(
                    r.novel, r.chapter_count, r.char_count, r.translated_count,
                    r.views_total, r.rating_avg, r.rating_count,
                )
    raise HTTPException(404, "novel not found")


@router.patch("/novels/{novel_id}", response_model=NovelOut)
async def patch_novel_route(
    novel_id: int, body: NovelPatch, _admin: User = Depends(require_admin)
) -> NovelOut:
    with get_session() as s:
        updated = update_novel(
            s,
            novel_id,
            title=body.title,
            title_en=body.title_en,
            author=body.author,
            description=body.description,
            tags=_join_tags(body.tags),
            status=body.status,
            source_lang=body.source_lang,
        )
        if updated is None:
            raise HTTPException(404, "novel not found")
    return await get_novel_route(novel_id)


@router.patch(
    "/novels/{novel_id}/glossary/{term_id}", response_model=GlossaryEntryOut
)
async def patch_glossary_term_route(
    novel_id: int,
    term_id: int,
    body: GlossaryPatch,
    _admin: User = Depends(require_admin),
) -> GlossaryEntryOut:
    """Edit a glossary rendering and/or lock it. Editing a rendering locks it
    unless ``locked`` is sent explicitly; locked terms survive re-translation."""
    with get_session() as s:
        t = update_term(
            s, novel_id, term_id, target_term=body.target_term, locked=body.locked
        )
        if t is None:
            raise HTTPException(404, "term not found")
        return GlossaryEntryOut(**term_dicts([t])[0])


@router.delete("/novels/{novel_id}")
async def delete_novel_route(
    novel_id: int, _admin: User = Depends(require_admin)
) -> dict:
    """Remove a book and everything derived from it."""
    with get_session() as s:
        if not delete_novel(s, novel_id):
            raise HTTPException(404, "novel not found")
    log.info("novel.deleted", novel_id=novel_id)
    return {"ok": True, "deleted": novel_id}


@router.get("/novels/{novel_id}/cover")
async def get_cover_route(novel_id: int, request: Request) -> Response:
    """The cover as WebP. Cacheable for a day; revalidates by ETag."""
    with get_session() as s:
        at = get_cover_updated_at(s, novel_id)
        if at is None:
            raise HTTPException(404, "no cover")
        etag = f'"{cover_version(novel_id, at)}"'
        headers = {"Cache-Control": "public, max-age=86400", "ETag": etag}
        sent = [t.strip().removeprefix("W/") for t in
                request.headers.get("if-none-match", "").split(",")]
        if etag in sent or "*" in sent:
            return Response(status_code=304, headers=headers)
        row = get_cover(s, novel_id)
        if row is None:
            raise HTTPException(404, "no cover")
        return Response(content=row.data, media_type=row.content_type, headers=headers)


async def _store_cover(novel_id: int, raw: bytes) -> None:
    try:
        cover = await process_cover(raw)
    except CoverError as e:
        raise HTTPException(400, str(e)) from e
    with get_session() as s:
        if get_novel(s, novel_id) is None:
            raise HTTPException(404, "novel not found")
        set_cover(
            s, novel_id, data=cover.data, width=cover.width,
            height=cover.height, content_type=cover.content_type,
        )


@router.put("/novels/{novel_id}/cover", response_model=NovelOut)
async def put_cover_route(
    novel_id: int, request: Request, _admin: User = Depends(require_admin)
) -> NovelOut:
    """Set the cover from a multipart ``file`` or a JSON ``{"url": ...}``."""
    with get_session() as s:
        if get_novel(s, novel_id) is None:
            raise HTTPException(404, "novel not found")
    ctype = request.headers.get("content-type", "").lower()
    if ctype.startswith("application/json"):
        try:
            body = CoverUrlIn.model_validate(await request.json())
        except Exception as e:
            raise HTTPException(422, "expected JSON body {\"url\": ...}") from e
        try:
            raw = await fetch_bytes_guarded(body.url, MAX_COVER_BYTES)
        except UnsafeURL as e:
            log.warning("cover_url.unsafe_url", reason=str(e))
            raise HTTPException(
                400,
                detail={
                    "code": "unsafe_url",
                    "detail": "This URL can't be fetched (only public http/https addresses are allowed).",
                },
            )
        except FetchTooLarge:
            raise HTTPException(413, "image is larger than 5 MB")
        except Exception as e:
            log.warning("cover_url.fetch_fail", err=str(e))
            raise HTTPException(400, "could not fetch the image") from e
    else:
        clen = request.headers.get("content-length", "")
        if clen.isdigit() and int(clen) > MAX_COVER_BYTES + 64 * 1024:
            raise HTTPException(413, "image is larger than 5 MB")
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(422, "missing file")
        raw = await upload.read(MAX_COVER_BYTES + 1)
        if len(raw) > MAX_COVER_BYTES:
            raise HTTPException(413, "image is larger than 5 MB")
    await _store_cover(novel_id, raw)
    return await get_novel_route(novel_id)


@router.delete("/novels/{novel_id}/cover")
async def delete_cover_route(
    novel_id: int, _admin: User = Depends(require_admin)
) -> dict:
    with get_session() as s:
        if not delete_cover(s, novel_id):
            raise HTTPException(404, "no cover")
    return {"ok": True}


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
                title_en=r.title_en,
                char_count=r.char_count,
                translated=r.translated,
                pieces_done=r.pieces_done,
            )
            for r in chapter_rows(s, novel_id, target_lang=target_lang)
        ]


@router.get("/novels/{novel_id}/chapters/{idx}", response_model=ChapterDetail)
async def get_chapter_route(
    novel_id: int,
    idx: int,
    request: Request,
    target_lang: str = "en",
    user: User | None = Depends(current_user_optional),
) -> ChapterDetail:
    """Read a chapter. Returns the saved translation; never calls the model.

    Signed-in readers have their position advanced to this chapter (never back).
    """
    with get_session() as s:
        chap = get_chapter_by_idx(s, novel_id, idx)
        if chap is None:
            raise HTTPException(404, "chapter not found")
        if user is not None:
            advance_progress(s, user.id, novel_id, idx)
        track_chapter_view(s, request, user, novel_id)
        tr = get_translation(s, chapter_id=chap.id, target_lang=target_lang)
        return ChapterDetail(
            idx=chap.idx,
            title=chap.title,
            title_en=tr.title if tr else None,
            char_count=chap.char_count,
            source_text=chap.source_text,
            translation=tr.text if tr else None,
            translated_with=tr.model if tr else None,
            critic_passes=tr.critic_passes if tr else None,
            complete=tr is not None and tr.pieces_done is None,
            pieces_done=tr.pieces_done if tr else None,
        )


_TITLE_BATCH = 40


@router.post(
    "/novels/{novel_id}/titles/translate", response_model=TitlesTranslateResult
)
async def translate_titles_route(
    novel_id: int, request: Request, admin: User = Depends(require_admin)
) -> TitlesTranslateResult:
    """Backfill translated titles for chapters that already have a complete
    English translation, plus the book title. Batched to save LLM quota."""
    llm = resolve_llm(request.headers, admin)
    with get_session() as s:
        novel = get_novel(s, novel_id)
        if novel is None:
            raise HTTPException(404, "novel not found")
        novel_title = novel.title
        need_novel = not novel.title_en
        glossary = [
            (t.source_term, t.target_term)
            for t in get_terms_for_chapters(
                s, novel_id, up_to_chapter=10**6, target_lang="en"
            )
        ]
        pending = [(tr.id, title) for tr, title in untitled_translations(s, novel_id)]

    done = 0
    for i in range(0, len(pending), _TITLE_BATCH):
        batch = pending[i : i + _TITLE_BATCH]
        out = await translate_titles_batch(llm, [t for _, t in batch], glossary)
        with get_session() as s:
            for (tr_id, _), en in zip(batch, out):
                row = s.get(Translation, tr_id)
                if en and row is not None and row.title is None:
                    row.title = en
                    done += 1

    novel_done = False
    if need_novel and novel_title.strip():
        en = await translate_title(llm, novel_title, glossary)
        if en:
            with get_session() as s:
                nv = get_novel(s, novel_id)
                if nv is not None and not nv.title_en:
                    update_novel(s, novel_id, title_en=en)
                    novel_done = True
    log.info("titles.translated", novel_id=novel_id, chapters=done, novel=novel_done)
    return TitlesTranslateResult(chapters=done, novel=novel_done)


# Uploads are held in memory before parsing, so cap them. A 20 MB text file is
# already a very long novel; anything bigger is a mistake or an attack.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_TEXT_SUFFIXES = {".txt", ".text", ".md"}
_EPUB_SUFFIXES = {".epub"}
_PDF_SUFFIXES = {".pdf"}


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
async def ingest_text(
    body: IngestTextIn, _user: User = Depends(current_user)
) -> IngestResult:
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
    _user: User = Depends(current_user),
) -> IngestResult:
    """Import a book from a .txt, .md, .epub or .pdf file and save it.

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
    if suffix not in _TEXT_SUFFIXES | _EPUB_SUFFIXES | _PDF_SUFFIXES:
        raise HTTPException(
            400,
            f"unsupported file type {suffix or '(none)'}; use .txt, .md, .epub or .pdf",
        )

    tmp_path: str | None = None
    cover_raw: bytes | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        if suffix in _EPUB_SUFFIXES:
            loader = load_epub_with_cover
        elif suffix in _PDF_SUFFIXES:
            loader = load_pdf
        else:
            loader = load_txt
        try:
            # Parsing a big PDF/EPUB is CPU-bound; keep it off the event loop.
            text = await asyncio.to_thread(loader, tmp_path)
            if isinstance(text, tuple):
                text, cover_raw = text
        except Exception as e:  # malformed archive, unreadable encoding, ...
            log.warning("upload.parse_fail", name=name, err=str(e))
            raise HTTPException(400, f"could not read {name}: {e}") from e
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    if not text.strip():
        raise HTTPException(400, f"no text found in {name}")

    result = _persist_novel(
        title=(title or Path(name).stem).strip()[:512],
        text=text,
        source_lang=source_lang,
        author=author,
        description=description,
        tags=[t for t in (tags or "").split(",") if t.strip()],
    )
    if cover_raw:
        # Best effort: a bad embedded image must never fail the import.
        try:
            await _store_cover(result.novel_id, cover_raw)
        except HTTPException as e:
            log.info("upload.cover_skipped", novel_id=result.novel_id, why=e.detail)
    return result


@router.post("/novels/ingest/url", response_model=IngestResult)
async def ingest_url(
    body: IngestUrlIn, _user: User = Depends(current_user)
) -> IngestResult:
    try:
        pages = await scrape_many(body.urls, concurrency=2)
    except UnsafeURL as e:
        # Specific reason stays in the log only (avoids a DNS/network oracle).
        log.warning("ingest_url.unsafe_url", reason=str(e))
        raise HTTPException(
            400,
            detail={
                "code": "unsafe_url",
                "detail": "This URL can't be imported (only public http/https addresses are allowed).",
            },
        )
    combined = "\n\n".join(p.text for p in pages if p.text)
    if not combined.strip():
        raise HTTPException(400, "scrape returned empty text")
    lang = body.source_lang or detect_lang(combined)
    # Split each page on its own: a page that yields exactly one chapter
    # has a known chapter URL; a page with several headed chapters does not.
    from ..ingest.splitter import ParsedChapter

    items: list[tuple[ParsedChapter, str | None]] = []
    for p in pages:
        if not p.text.strip():
            continue
        got = split_chapters(p.text) or [
            ParsedChapter(idx=0, title=p.title, text=p.text)
        ]
        url = p.url[:1024] if len(got) == 1 else None
        items.extend((c, url) for c in got)
    with get_session() as s:
        novel = create_novel(s, title=body.title, source_lang=lang)
        update_novel(
            s, novel.id, source_index_url=(body.index_url or body.urls[0])[:1024]
        )
        n = 0
        for i, (c, url) in enumerate(items):
            insert_chapter(
                s,
                novel_id=novel.id,
                idx=i,
                title=c.title,
                source_text=c.text,
                source_url=url,
            )
            n += 1
        return IngestResult(novel_id=novel.id, chapters_added=n)


@router.post("/novels/{novel_id}/check-updates", response_model=UpdateCheckResult)
async def check_updates(
    novel_id: int, _admin: User = Depends(require_admin)
) -> UpdateCheckResult:
    """Scrape chapters that appeared on the source index since the import."""
    try:
        outcome = await check_novel_updates(novel_id)
    except NovelNotFound:
        raise HTTPException(404, "novel not found")
    except NoChapterPattern as e:
        raise HTTPException(
            409, detail={"code": "no_chapter_pattern", "detail": str(e)}
        )
    except UpdateCheckUnavailable as e:
        raise HTTPException(409, str(e))
    except UnsafeURL as e:
        log.warning("check_updates.unsafe_url", reason=str(e))
        raise HTTPException(
            400,
            detail={
                "code": "unsafe_url",
                "detail": "The source URL can't be fetched (only public http/https addresses are allowed).",
            },
        )
    hint = None
    if not outcome.embedded:
        hint = (
            "Chapters were added but not embedded; run "
            f'`make reembed ARGS="--novel {novel_id}"`.'
        )
    return UpdateCheckResult(
        added=outcome.added, embedded=outcome.embedded, hint=hint
    )


@router.post("/novels/embed", response_model=EmbedResult)
async def embed(
    body: EmbedIn, _user: User = Depends(current_user)
) -> EmbedResult:
    with get_session() as s:
        novel = get_novel(s, body.novel_id)
        if novel is None:
            raise HTTPException(404, "novel not found")
        chaps = get_chapters(s, body.novel_id, up_to=body.to_chapter)
        chaps = [c for c in chaps if c.idx >= body.from_chapter]
    n = await embed_chapters(body.novel_id, chaps)
    return EmbedResult(points=n)

