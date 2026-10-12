"""Bulk table-of-contents import: discover chapter links, scrape them in the
background at one request per second, and report progress through an
``ImportJob`` row.
"""
from __future__ import annotations

import asyncio
from sqlalchemy import func, select

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
    """Startup: a job left running died with the previous process."""
    with get_session() as s:
        jobs = list(s.scalars(select(ImportJob).where(ImportJob.status.in_(ACTIVE))).all())
        for j in jobs:
            j.status = "failed"
            j.error = "server restarted"
        return len(jobs)


def _set(job_id: int, **fields) -> None:
    with get_session() as s:
        job = s.get(ImportJob, job_id)
        if job is not None:
            for k, v in fields.items():
                setattr(job, k, v)


def start_job(job_id: int, novel_id: int, urls: list[str]) -> None:
    task = asyncio.create_task(run_job(job_id, novel_id, urls))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_job(job_id: int, novel_id: int, urls: list[str]) -> None:
    try:
        _set(job_id, status="running")
        added = 0
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
        try:
            await embed_chapters(novel_id, chaps)
        except Exception as e:  # noqa: BLE001 - chapters are saved; embedding is retryable
            log.error("toc_import.embed_failed", novel_id=novel_id, err=str(e))
        _set(job_id, status="done")
    except Exception as e:  # noqa: BLE001
        log.error("toc_import.failed", job_id=job_id, err=str(e))
        _set(job_id, status="failed", error=str(e)[:500])


def create_job_and_novel(
    *, user_id: int, title: str, lang: str, index_url: str, visibility: str, total: int
) -> tuple[int, int]:
    """Create the (empty) novel and its queued job; returns (job_id, novel_id)."""
    from ..storage.repository import create_novel, update_novel

    with get_session() as s:
        novel = create_novel(
            s, title=title, source_lang=lang, visibility=visibility, owner_id=user_id
        )
        update_novel(s, novel.id, source_index_url=index_url[:1024])
        job = ImportJob(user_id=user_id, novel_id=novel.id, status="queued", total=total)
        s.add(job)
        s.flush()
        return job.id, novel.id
