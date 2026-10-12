"""Per-book machine-translation job.

Every added book (upload, URL, TOC import, seed) gets one: it translates the
book title, author and description, then each chapter's title and text in
order (chapter 0 first), saving each chapter as ``translations`` rows with
``engine='mt'``. Progress lives in ``mt_jobs`` (one row per book; a sibling of
``import_jobs`` so import quotas and listings are untouched).

Never fails an import: the job runs in the background and every error is
contained here. A sweep re-enqueues books that still have untranslated
chapters (new books from other processes, seeds, jobs interrupted by a
restart, or paused by the circuit breaker).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, select, text

from ..common.logging import get_logger
from ..ingest.toc_import import BOOT_ID
from ..storage.db import get_session
from ..storage.models import Chapter, MtJob, Novel, Translation
from ..storage.repository import get_terms_for_chapters, update_novel, upsert_translation
from . import gate
from .provider import MTBlocked, MTError, Provider, get_provider

log = get_logger(__name__)

ACTIVE = ("queued", "running")
STALE_AFTER = timedelta(minutes=10)
RETRY_FAILED_AFTER = timedelta(hours=1)
SWEEP_INTERVAL_S = 3600.0
SWEEP_FIRST_DELAY_S = 30.0
MAX_PER_SWEEP = 3
MAX_CONSECUTIVE_ERRORS = 5
MIN_TERM_LEN = 2
LOCK_MT_JOBS = 7003  # advisory-lock namespace

_tasks: set[asyncio.Task] = set()
_sem: asyncio.Semaphore | None = None
_sem_loop: asyncio.AbstractEventLoop | None = None


def _semaphore() -> asyncio.Semaphore:
    """One book at a time per process (the provider limiter is global anyway)."""
    global _sem, _sem_loop
    loop = asyncio.get_running_loop()
    if _sem is None or _sem_loop is not loop:
        _sem, _sem_loop = asyncio.Semaphore(1), loop
    return _sem


def source_code(lang: str | None) -> str | None:
    """Provider source language code, or None when there is nothing to do."""
    lang = (lang or "zh").lower()
    if lang.startswith("en"):
        return None
    if lang.startswith("zh"):
        return "zh-CN"
    return lang.split("-")[0]


def apply_glossary(
    text_: str, terms: list[tuple[str, str, int]], chapter_idx: int
) -> str:
    """Replace known source terms by their English rendering before sending.

    Longest term first (so 青云宗 wins over 青云), only terms introduced at or
    before this chapter. Terms shorter than two characters are skipped: a
    single-character match is more often part of another word than the name.
    """
    for src, tgt, first in sorted(terms, key=lambda t: -len(t[0])):
        if first <= chapter_idx and len(src) >= MIN_TERM_LEN and tgt and src in text_:
            text_ = text_.replace(src, tgt)
    return text_


# --- job rows ---------------------------------------------------------------

def _fresh_active(job: MtJob | None) -> bool:
    if job is None or job.status not in ACTIVE:
        return False
    if job.boot_id == BOOT_ID:
        return True
    updated = job.updated_at
    if updated is not None and updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return updated is not None and updated > datetime.now(timezone.utc) - STALE_AFTER


def ensure_job(novel_id: int) -> bool:
    """Queue a job unless one is already active. True if this call queued it."""
    with get_session() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(:ns, :k)"),
                  {"ns": LOCK_MT_JOBS, "k": novel_id})
        if s.get(Novel, novel_id) is None:
            return False
        job = s.get(MtJob, novel_id)
        if _fresh_active(job):
            return False
        if job is None:
            s.add(MtJob(novel_id=novel_id, status="queued", boot_id=BOOT_ID))
        else:
            job.status, job.error, job.boot_id = "queued", None, BOOT_ID
        s.flush()
        return True


def _set(novel_id: int, **fields) -> None:
    with get_session() as s:
        job = s.get(MtJob, novel_id)
        if job is not None:
            for k, v in fields.items():
                setattr(job, k, v)


def enqueue(novel_id: int, *, start: bool = True) -> bool:
    """Queue (and, inside a running event loop, start) a book's MT job.

    Safe to call from anywhere and never raises: MT problems must not fail
    whatever the caller was doing. Does nothing when MT is off.
    """
    try:
        if get_provider() is None:
            return False
        if not ensure_job(novel_id):
            return False
        if start:
            try:
                task = asyncio.get_running_loop().create_task(run_job(novel_id))
            except RuntimeError:
                return True  # no loop (CLI): the sweep will pick the queued job up
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("mt.enqueue_failed", novel_id=novel_id, err=str(e))
        return False


def status_for(novel_id: int) -> dict:
    """{status, done, total}: live chapter counts plus the job's status."""
    with get_session() as s:
        total = s.scalar(
            select(func.count()).select_from(Chapter).where(
                Chapter.novel_id == novel_id, Chapter.char_count > 0
            )
        ) or 0
        done = s.scalar(
            select(func.count(func.distinct(Translation.chapter_id)))
            .join(Chapter, Chapter.id == Translation.chapter_id)
            .where(
                Chapter.novel_id == novel_id,
                Chapter.char_count > 0,
                Translation.engine == "mt",
                Translation.target_lang == "en",
                Translation.text != "",
            )
        ) or 0
        job = s.get(MtJob, novel_id)
        if job is not None and job.status in ACTIVE and not _fresh_active(job):
            status = "failed"  # orphaned by a restart; the sweep will requeue it
        elif job is not None:
            status = job.status
        else:
            status = "done" if total and done >= total else "none"
        if status == "done" and done < total:
            status = "failed" if job is not None and job.error else "none"
        return {"status": status, "done": int(done), "total": int(total)}


# --- the job ----------------------------------------------------------------

async def run_job(novel_id: int) -> None:
    """Run one book's job; always leaves the job row terminal. Never raises."""
    try:
        provider = get_provider()
        if provider is None:
            return
        async with _semaphore():
            await _run(novel_id, provider)
    except Exception as e:  # noqa: BLE001
        log.error("mt.job_failed", novel_id=novel_id, err=str(e))
        _set(novel_id, status="failed", error="Machine translation failed.")
    finally:
        try:
            with get_session() as s:
                job = s.get(MtJob, novel_id)
                if job is not None and job.status in ACTIVE:
                    job.status = "failed"
                    job.error = job.error or "Machine translation was interrupted."
        except Exception as e:  # noqa: BLE001
            log.error("mt.finalize_failed", novel_id=novel_id, err=str(e))


async def _translate_meta(novel_id: int, provider: Provider, src: str) -> None:
    with get_session() as s:
        n = s.get(Novel, novel_id)
        if n is None:
            return
        want = {
            "title_en": n.title if not n.title_en else None,
            "author_en": n.author if not n.author_en else None,
            "description_en": n.description if not n.description_en else None,
        }
    want = {k: v for k, v in want.items() if v and v.strip()}
    if not want:
        return
    out = await provider.translate(list(want.values()), src, "en")
    fields = {
        k: o.strip()
        for k, o in zip(want, out)
        if o and o.strip()
    }
    fields = {
        k: (v[:512] if k == "title_en" else v[:256] if k == "author_en" else v)
        for k, v in fields.items()
    }
    with get_session() as s:
        n = s.get(Novel, novel_id)
        if n is None:
            return
        # Never overwrite a value an admin or the AI path set meanwhile.
        update_novel(s, novel_id, **{k: v for k, v in fields.items() if not getattr(n, k)})


async def _run(novel_id: int, provider: Provider) -> None:
    with get_session() as s:
        novel = s.get(Novel, novel_id)
        if novel is None:
            return
        src = source_code(novel.source_lang)
        chapters = [
            (c.id, c.idx, c.title, c.source_text)
            for c in s.scalars(
                select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.idx)
            ).all()
            if c.source_text and c.source_text.strip()
        ]
        have = set(
            s.scalars(
                select(Translation.chapter_id)
                .join(Chapter, Chapter.id == Translation.chapter_id)
                .where(
                    Chapter.novel_id == novel_id,
                    Translation.engine == "mt",
                    Translation.target_lang == "en",
                    Translation.text != "",
                )
            ).all()
        )
        terms = [
            (t.source_term, t.target_term, t.first_chapter)
            for t in get_terms_for_chapters(s, novel_id, up_to_chapter=10**6)
        ]
    if src is None:
        _set(novel_id, status="done", total=0, done=0, error=None)
        return
    total = len(chapters)
    done = sum(1 for c in chapters if c[0] in have)
    _set(novel_id, status="running", boot_id=BOOT_ID, total=total, done=done, error=None)

    try:
        await _translate_meta(novel_id, provider, src)
    except MTBlocked as e:
        _set(novel_id, status="failed", error=f"paused: {e}")
        return
    except MTError as e:
        log.warning("mt.meta_failed", novel_id=novel_id, err=str(e))

    skipped = errors = 0
    for chap_id, idx, title, source in chapters:
        if chap_id in have:
            continue
        pieces = [apply_glossary(source, terms, idx)]
        if title and title.strip():
            pieces.insert(0, apply_glossary(title, terms, idx))
        try:
            out = await provider.translate(pieces, src, "en")
        except MTBlocked as e:
            log.error("mt.blocked", novel_id=novel_id, chapter_idx=idx, err=str(e))
            _set(novel_id, status="failed", error=f"paused: {e}")
            return
        except MTError as e:
            log.warning("mt.chapter_failed", novel_id=novel_id, chapter_idx=idx, err=str(e))
            skipped += 1
            errors += 1
            if errors >= MAX_CONSECUTIVE_ERRORS:
                _set(novel_id, status="failed", error="too many translation errors")
                return
            continue
        errors = 0
        body = out[-1].strip() if out else ""
        title_en = out[0].strip()[:512] if len(out) > 1 and out[0].strip() else None
        if not body:
            skipped += 1
            continue
        with get_session() as s:
            upsert_translation(
                s, chapter_id=chap_id, target_lang="en", text=body,
                model=provider.name, critic_passes=0, title=title_en, engine="mt",
            )
        done += 1
        _set(novel_id, done=done)
    if skipped:
        _set(novel_id, status="failed", error=f"{skipped} chapter(s) could not be translated")
    else:
        _set(novel_id, status="done", error=None)
    log.info("mt.job_done", novel_id=novel_id, chapters=done, skipped=skipped)


# --- sweep --------------------------------------------------------------------

def find_pending(limit: int = MAX_PER_SWEEP) -> list[int]:
    """Books with untranslated chapters and no live or recently failed job."""
    now = datetime.now(timezone.utc)
    total = (
        select(Chapter.novel_id.label("nid"), func.count(Chapter.id).label("n"))
        .where(Chapter.char_count > 0)
        .group_by(Chapter.novel_id)
        .subquery()
    )
    done = (
        select(Chapter.novel_id.label("nid"),
               func.count(func.distinct(Translation.chapter_id)).label("n"))
        .join(Translation, Translation.chapter_id == Chapter.id)
        .where(Translation.engine == "mt", Translation.target_lang == "en",
               Translation.text != "", Chapter.char_count > 0)
        .group_by(Chapter.novel_id)
        .subquery()
    )
    live = exists().where(
        MtJob.novel_id == Novel.id,
        (
            (MtJob.status.in_(ACTIVE)
             & ((MtJob.boot_id == BOOT_ID) | (MtJob.updated_at > now - STALE_AFTER)))
            | ((MtJob.status == "failed") & (MtJob.updated_at > now - RETRY_FAILED_AFTER))
        ),
    )
    stmt = (
        select(Novel.id)
        .join(total, total.c.nid == Novel.id)
        .outerjoin(done, done.c.nid == Novel.id)
        .where(total.c.n > func.coalesce(done.c.n, 0), ~live,
               ~Novel.source_lang.ilike("en%"))
        .order_by(Novel.id)
        .limit(limit)
    )
    with get_session() as s:
        return list(s.scalars(stmt).all())


def sweep_once(limit: int = MAX_PER_SWEEP) -> int:
    """Enqueue (and start) jobs for pending books; returns how many."""
    if get_provider() is None or gate.paused():
        return 0
    n = 0
    for nid in find_pending(limit):
        if enqueue(nid):
            n += 1
    return n


async def sweep_loop(
    interval_s: float = SWEEP_INTERVAL_S, first_delay_s: float = SWEEP_FIRST_DELAY_S
) -> None:
    await asyncio.sleep(first_delay_s)
    while True:
        try:
            n = await asyncio.to_thread(find_pending, MAX_PER_SWEEP)
            if n and get_provider() is not None and not gate.paused():
                started = sum(1 for nid in n if enqueue(nid))
                if started:
                    log.info("mt.sweep_enqueued", count=started)
        except Exception as e:  # noqa: BLE001
            log.warning("mt.sweep_failed", err=str(e))
        await asyncio.sleep(interval_s)
