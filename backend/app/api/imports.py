"""Bulk table-of-contents import and its background-job status routes."""
from __future__ import annotations

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException

from ..auth.deps import current_user
from ..common.logging import get_logger
from ..ingest import toc_import
from ..ingest.cover_fetch import extract_cover_url
from ..ingest.lang import detect_lang
from ..ingest.scraper import UnsafeURL, fetch_html
from ..storage.db import get_session
from ..storage.models import ImportJob, User
from .access import visible_novel_or_404
from .novels import _import_visibility
from .schemas import ImportJobOut, IngestTocAccepted, IngestTocIn

log = get_logger(__name__)
router = APIRouter()


def _job_out(j: ImportJob) -> ImportJobOut:
    return ImportJobOut(
        id=j.id, novel_id=j.novel_id, status=j.status, total=j.total, done=j.done,
        error=j.error, created_at=j.created_at, updated_at=j.updated_at,
    )


@router.post("/novels/ingest/toc", response_model=IngestTocAccepted, status_code=202)
async def ingest_toc(
    body: IngestTocIn, user: User = Depends(current_user)
) -> IngestTocAccepted:
    vis = _import_visibility(user, body.visibility)
    try:
        html = await fetch_html(body.index_url)
    except UnsafeURL as e:
        log.warning("ingest_toc.unsafe_url", reason=str(e))
        raise HTTPException(
            400,
            detail={
                "code": "unsafe_url",
                "detail": "This URL can't be imported (only public http/https addresses are allowed).",
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning("ingest_toc.fetch_failed", err=str(e))
        raise HTTPException(400, "The table-of-contents page could not be fetched.")
    urls = toc_import.discover_toc(html, body.index_url, body.max_chapters)
    if not urls:
        raise HTTPException(400, "No chapter links were found on that page.")
    soup = BeautifulSoup(html, "lxml")
    title = (body.title or "").strip()
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    title = (title or "Untitled import")[:512]
    lang = detect_lang(soup.get_text(" ", strip=True)) or "zh"
    try:
        # Cap check + insert are one locked transaction (after the slow fetch).
        job_id, novel_id = toc_import.create_job_and_novel(
            user_id=user.id, title=title, lang=lang, index_url=body.index_url,
            visibility=vis, total=len(urls),
        )
    except toc_import.TooManyJobs:
        raise HTTPException(
            429, f"At most {toc_import.MAX_RUNNING_PER_USER} imports can run at once."
        )
    try:
        cover_url = extract_cover_url(html, body.index_url)
    except Exception:  # noqa: BLE001 - a cover hint never fails an import
        cover_url = None
    toc_import.start_job(job_id, novel_id, urls, cover_url)
    return IngestTocAccepted(job_id=job_id)


@router.get("/imports/{job_id}", response_model=ImportJobOut)
async def get_import(job_id: int, user: User = Depends(current_user)) -> ImportJobOut:
    with get_session() as s:
        job = s.get(ImportJob, job_id)
        if job is None or not (user.is_admin or job.user_id == user.id):
            raise HTTPException(404, "import not found")
        if job.novel_id is not None:
            visible_novel_or_404(s, job.novel_id, user)
        return _job_out(job)


@router.get("/imports", response_model=list[ImportJobOut])
async def list_imports(
    mine: bool = False, user: User = Depends(current_user)
) -> list[ImportJobOut]:
    from sqlalchemy import select

    with get_session() as s:
        q = select(ImportJob).order_by(ImportJob.id.desc()).limit(100)
        if mine or not user.is_admin:
            q = q.where(ImportJob.user_id == user.id)
        return [_job_out(j) for j in s.scalars(q).all()]
