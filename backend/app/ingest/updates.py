"""Find and import chapters added to a URL-imported novel's source site."""
from __future__ import annotations

from collections import Counter
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup
from sqlalchemy import func, select

from ..common.logging import get_logger
from ..embed.pipeline import embed_chapters
from ..storage.db import get_session
from ..storage.models import Chapter, Novel
from ..storage.repository import insert_chapter
from .scraper import fetch_html, scrape_many

log = get_logger(__name__)

MAX_NEW_PER_RUN = 50


class NovelNotFound(LookupError):
    pass


class UpdateCheckUnavailable(ValueError):
    """The novel has no recorded source to check against."""


def _dir(url: str) -> str:
    path = urlsplit(url).path
    return path.rsplit("/", 1)[0] + "/"


def discover_links(html: str, index_url: str, known: list[str]) -> list[str]:
    """Same-host links on the index page, in page order, de-duplicated.

    Narrowed to the directory the already-imported chapters live in, so site
    navigation (home, login, genre lists) is not mistaken for chapters.
    """
    host = urlsplit(index_url).hostname
    dirs = Counter(_dir(u) for u in known if urlsplit(u).hostname == host)
    want_dir = dirs.most_common(1)[0][0] if dirs else _dir(index_url)
    seen: set[str] = set(known)
    seen.add(urldefrag(index_url)[0])
    out: list[str] = []
    for a in BeautifulSoup(html, "lxml").find_all("a", href=True):
        url = urldefrag(urljoin(index_url, a["href"].strip()))[0]
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.hostname != host:
            continue
        if not parts.path.startswith(want_dir) or parts.path == want_dir:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


async def check_novel_updates(novel_id: int) -> int:
    """Scrape and append chapters not yet imported; returns how many."""
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

    html = await fetch_html(index_url)
    new_urls = discover_links(html, index_url, known)[:MAX_NEW_PER_RUN]
    if not new_urls:
        return 0
    pages = [p for p in await scrape_many(new_urls, concurrency=2) if p.text.strip()]
    if not pages:
        return 0

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
    await embed_chapters(novel_id, chaps)
    log.info("novel.updates_added", novel_id=novel_id, added=len(pages))
    return len(pages)
