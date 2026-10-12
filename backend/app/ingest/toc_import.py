"""Bulk table-of-contents import: discover chapter links, scrape them in the
background at one request per second, and report progress through an
``ImportJob`` row.
"""
from __future__ import annotations

import asyncio
import uuid
import weakref
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from ..common.logging import get_logger
from ..embed.pipeline import embed_chapters
from ..storage.db import get_session
from ..storage.models import Chapter, ImportJob, Novel
from ..storage.repository import insert_chapter
from .scraper import scrape_url
from .updates import discover_links

log = get_logger(__name__)

# Politeness: one chapter request per second (tests set this to 0).
REQUEST_DELAY = 1.0
MAX_RUNNING_PER_USER = 2
ACTIVE = ("queued", "running")
MAX_CONCURRENT_JOBS = 2  # process-wide
JOB_TIMEOUT_S = 2 * 3600
STALE_AFTER = timedelta(minutes=10)
GENERIC_ERROR = "The import failed. Please try again later."
EMBED_WARNING = "Chapters were imported, but search indexing failed and will need a retry."

# Identifies this process; jobs created by another boot are orphans.
BOOT_ID = uuid.uuid4().hex

# Advisory-lock namespaces (first key of the two-int form).
LOCK_USER_JOBS = 7001
LOCK_SWEEP = 7002


class TooManyJobs(Exception):
    """The user already has MAX_RUNNING_PER_USER active imports."""

_sems: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _sems.get(loop)
    if sem is None:
        sem = _sems[loop] = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    return sem

# Strong references so a fire-and-forget task is not garbage collected.
_tasks: set[asyncio.Task] = set()


def discover_toc(html: str, index_url: str, limit: int) -> list[str]:
    """Chapter URLs on a table-of-contents page, in page order."""
    return discover_links(html, index_url, [])[:limit]


def active_jobs(session, user_id: int) -> int:
    return session.scalar(
        select(func.count()).select_from(ImportJob).where(
            ImportJob.user_id == user_id, ImportJob.status.in_(ACTIVE)
        )
    ) or 0


def mark_interrupted_jobs() -> int:
    """Fail active jobs orphaned by another process boot.

    Only jobs with a different (or missing) boot id that have not been touched
    for STALE_AFTER are failed, and only one process sweeps at a time.
    """
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    with get_session() as s:
        if not s.scalar(text("SELECT pg_try_advisory_xact_lock(:k, 0)"), {"k": LOCK_SWEEP}):
            return 0
        jobs = list(
            s.scalars(
                select(ImportJob).where(
                    ImportJob.status.in_(ACTIVE),
                    ImportJob.updated_at < cutoff,
                    (ImportJob.boot_id.is_(None)) | (ImportJob.boot_id != BOOT_ID),
                )
            ).all()
        )
        for j in jobs:
            j.status = "failed"
            j.error = "server restarted"
        return len(jobs)


async def sweep_loop(interval_s: float = 300.0) -> None:
    """Periodically fail orphaned jobs (a crash within STALE_AFTER of a restart)."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            n = await asyncio.to_thread(mark_interrupted_jobs)
            if n:
                log.warning("toc_import.orphans_failed", count=n)
        except Exception as e:  # noqa: BLE001
            log.warning("toc_import.sweep_failed", err=str(e))


def _set(job_id: int, **fields) -> None:
    with get_session() as s:
        job = s.get(ImportJob, job_id)
        if job is not None:
            for k, v in fields.items():
                setattr(job, k, v)


def start_job(
    job_id: int, novel_id: int, urls: list[str], cover_url: str | None = None
) -> None:
    task = asyncio.create_task(run_job(job_id, novel_id, urls, cover_url))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_job(
    job_id: int, novel_id: int, urls: list[str], cover_url: str | None = None
) -> None:
    """Run one import; always leaves the job in a terminal status."""
    try:
        async with _semaphore():
            await asyncio.wait_for(
                _run(job_id, novel_id, urls, cover_url), JOB_TIMEOUT_S
            )
    except asyncio.TimeoutError:
        log.error("toc_import.timeout", job_id=job_id)
        _set(job_id, status="failed", error="The import took too long and was stopped.")
    except Exception as e:  # noqa: BLE001
        log.error("toc_import.failed", job_id=job_id, err=str(e))
        _set(job_id, status="failed", error=GENERIC_ERROR)
    finally:
        try:
            with get_session() as s:
                job = s.get(ImportJob, job_id)
                if job is not None and job.status in ACTIVE:
                    job.status = "failed"
                    job.error = job.error or GENERIC_ERROR
        except Exception as e:  # noqa: BLE001
            log.error("toc_import.finalize_failed", job_id=job_id, err=str(e))


async def _run(
    job_id: int, novel_id: int, urls: list[str], cover_url: str | None = None
) -> None:
    _set(job_id, status="running", boot_id=BOOT_ID)
    added = 0
    page_cover: str | None = None
    for i, url in enumerate(urls):
        if i and REQUEST_DELAY:
            await asyncio.sleep(REQUEST_DELAY)
        try:
            page = await scrape_url(url)  # SSRF-guarded on every fetch
        except Exception as e:  # noqa: BLE001 - one bad page is skipped
            log.warning("toc_import.page_skipped", url=url, err=str(e))
            page = None
        if page is not None and page.text.strip():
            with get_session() as s:
                insert_chapter(
                    s, novel_id=novel_id, idx=added, title=page.title,
                    source_text=page.text, source_url=page.url[:1024],
                )
            added += 1
            page_cover = page_cover or page.cover_url
        _set(job_id, done=i + 1)
    if added == 0:
        _set(job_id, status="failed", error="No chapter text could be fetched.")
        return
    with get_session() as s:
        chaps = list(
            s.scalars(
                select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.idx)
            ).all()
        )
        s.expunge_all()
    warning = None
    try:
        await embed_chapters(novel_id, chaps)
    except Exception as e:  # noqa: BLE001 - chapters are saved; embedding is retryable
        log.error("toc_import.embed_failed", novel_id=novel_id, err=str(e))
        warning = EMBED_WARNING
    _set(job_id, status="done", error=warning)
    _after_import(novel_id, [cover_url, page_cover])


def _after_import(novel_id: int, cover_candidates: list[str | None]) -> None:
    """Machine translation and a cover, both background and best effort."""
    from ..mt import job as mt_job
    from .cover_fetch import spawn_auto_cover

    mt_job.enqueue(novel_id)
    spawn_auto_cover(novel_id, image_urls=cover_candidates)


def create_job_and_novel(
    *, user_id: int, title: str, lang: str, index_url: str, visibility: str, total: int
) -> tuple[int, int]:
    """Create the (empty) novel and its queued job; returns (job_id, novel_id).

    The per-user cap is enforced here, in the same transaction as the insert,
    under a per-user advisory lock, so concurrent requests cannot both pass.
    """
    from ..storage.repository import create_novel, update_novel

    with get_session() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(:ns, :uid)"),
                  {"ns": LOCK_USER_JOBS, "uid": user_id})
        if active_jobs(s, user_id) >= MAX_RUNNING_PER_USER:
            raise TooManyJobs()
        novel = create_novel(
            s, title=title, source_lang=lang, visibility=visibility, owner_id=user_id
        )
        update_novel(s, novel.id, source_index_url=index_url[:1024])
        job = ImportJob(
            user_id=user_id, novel_id=novel.id, status="queued", total=total,
            boot_id=BOOT_ID,
        )
        s.add(job)
        s.flush()
        return job.id, novel.id
