"""Find and import chapters added to a URL-imported novel's source site."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import func, select

from ..common.logging import get_logger
from ..embed.pipeline import embed_chapters
from ..storage.db import get_session
from ..storage.models import Chapter, Novel
from ..storage.repository import insert_chapter
from .scraper import ScrapedPage, UnsafeURL, fetch_html, scrape_url

log = get_logger(__name__)

MAX_NEW_PER_RUN = 20


class NovelNotFound(LookupError):
    pass


class UpdateCheckUnavailable(ValueError):
    """The novel has no recorded source to check against."""


class NoChapterPattern(ValueError):
    """The known chapter URLs share no directory, so none can be told apart."""


@dataclass
class UpdateOutcome:
    added: int
    embedded: bool = True


def _segments(url: str) -> list[str]:
    return urlsplit(url).path.split("/")[1:]


def chapter_pattern(known: list[str], host: str | None) -> tuple[list[str], set[int]] | None:
    """(shared directory segments, allowed path-segment counts) of the known
    chapter URLs, or None when they share nothing deeper than "/"."""
    segs = [_segments(u) for u in known if urlsplit(u).hostname == host]
    if not segs:
        return None
    prefix = segs[0][:-1]
    for sg in segs[1:]:
        n = 0
        while n < len(prefix) and n < len(sg) - 1 and prefix[n] == sg[n]:
            n += 1
        prefix = prefix[:n]
    if not prefix:
        return None
    return prefix, {len(sg) for sg in segs}


def discover_links(html: str, index_url: str, known: list[str]) -> list[str]:
    """Same-host links on the index page, in page order, de-duplicated.

    Candidates must sit under the directory the imported chapters share and
    have the same path depth as them, so site navigation (home, login, genre
    lists) is not mistaken for chapters. Known URLs with no shared directory
    give no pattern to match, so nothing is discovered.
    """
    host = urlsplit(index_url).hostname
    if known:
        pat = chapter_pattern(known, host)
        if pat is None:
            return []
        prefix, counts = pat
    else:
        prefix, counts = _segments(index_url)[:-1], None
    seen: set[str] = set(known)
    seen.add(urldefrag(index_url)[0])
    out: list[str] = []
    for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
        url = urldefrag(urljoin(index_url, a["href"].strip()))[0]
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.hostname != host:
            continue
        segs = _segments(url)
        if segs[: len(prefix)] != prefix or len(segs) <= len(prefix) or not segs[-1]:
            continue
        if counts is not None and len(segs) not in counts:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


async def _scrape_safe(urls: list[str], concurrency: int = 2) -> list[ScrapedPage]:
    """Scrape each URL; one blocked or failing page is skipped, not fatal."""
    sem = asyncio.Semaphore(concurrency)

    async def one(u: str) -> ScrapedPage | None:
        async with sem:
            try:
                return await scrape_url(u)
            except UnsafeURL as e:
                log.warning("novel.update_url_skipped", url=u, reason=str(e))
            except Exception as e:  # noqa: BLE001
                log.error("scrape.fail", url=u, err=str(e))
            return None

    return [p for p in await asyncio.gather(*(one(u) for u in urls)) if p]


async def check_novel_updates(novel_id: int) -> UpdateOutcome:
    """Scrape and append chapters not yet imported."""
    with get_session() as s:
        novel = s.get(Novel, novel_id)
        if novel is None:
            raise NovelNotFound(novel_id)
        index_url = novel.source_index_url
        known = list(
            s.scalars(
                select(Chapter.source_url).where(
                    Chapter.novel_id == novel_id, Chapter.source_url.is_not(None)
                )
            ).all()
        )
    if not index_url:
        raise UpdateCheckUnavailable("this novel was not imported from a URL")
    if not known:
        raise UpdateCheckUnavailable(
            "the imported chapters' URLs were not recorded, so new ones cannot be told apart"
        )

    if chapter_pattern(known, urlsplit(index_url).hostname) is None:
        raise NoChapterPattern(
            "the imported chapters' URLs share no directory, so new chapters cannot be told apart from other links"
        )

    html = await fetch_html(index_url)
    new_urls = discover_links(html, index_url, known)[:MAX_NEW_PER_RUN]
    if not new_urls:
        return UpdateOutcome(0)
    pages = [p for p in await _scrape_safe(new_urls) if p.text.strip()]
    if not pages:
        return UpdateOutcome(0)

    with get_session() as s:
        top = s.scalar(
            select(func.max(Chapter.idx)).where(Chapter.novel_id == novel_id)
        )
        next_idx = 0 if top is None else top + 1
        for i, p in enumerate(pages):
            insert_chapter(
                s,
                novel_id=novel_id,
                idx=next_idx + i,
                title=p.title,
                source_text=p.text,
                source_url=p.url[:1024],
            )
        chaps = list(
            s.scalars(
                select(Chapter)
                .where(Chapter.novel_id == novel_id, Chapter.idx >= next_idx)
                .order_by(Chapter.idx)
            ).all()
        )
        s.expunge_all()
    embedded = True
    try:
        await embed_chapters(novel_id, chaps)
    except Exception as e:  # noqa: BLE001 - chapters are committed; embedding is retryable
        embedded = False
        log.error("novel.updates_embed_failed", novel_id=novel_id, err=str(e))
    log.info("novel.updates_added", novel_id=novel_id, added=len(pages), embedded=embedded)
    return UpdateOutcome(len(pages), embedded)
