"""Backfill covers for books that have none.

    python -m app.scripts.fill_covers [--novel ID]

Web-imported books: og:image / twitter:image / first large <img> on the
book's index page. Public ownerless books (the seeded classics): Wikidata, by
original title. All fetches are SSRF-guarded; a book with no luck is skipped.
"""
from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlsplit

from sqlalchemy import select

from ..ingest.cover_fetch import auto_cover
from ..storage.db import get_session, init_engine
from ..storage.models import Novel, NovelCover

# Pages on these sites share one generic site logo as og:image: not a cover.
GENERIC_IMAGE_HOSTS = ("wikisource.org", "wikipedia.org", "wikimedia.org")


def _is_generic(url: str | None) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in GENERIC_IMAGE_HOSTS)


def books_without_cover(only: int | None = None) -> list[tuple[int, str, str | None, bool]]:
    """(id, title, index/source url, is_seed_classic) for books lacking a cover."""
    with get_session() as s:
        stmt = (
            select(Novel.id, Novel.title, Novel.source_index_url, Novel.source_url,
                   Novel.visibility, Novel.owner_id)
            .outerjoin(NovelCover, NovelCover.novel_id == Novel.id)
            .where(NovelCover.novel_id.is_(None))
            .order_by(Novel.id)
        )
        if only is not None:
            stmt = stmt.where(Novel.id == only)
        return [
            (nid, title, index_url or src_url, vis == "public" and owner is None)
            for nid, title, index_url, src_url, vis, owner in s.execute(stmt).all()
        ]


async def fill_covers(only: int | None = None) -> dict[int, str]:
    """Returns {novel_id: title} for books that got a cover."""
    got: dict[int, str] = {}
    for nid, title, url, seed in books_without_cover(only):
        pages = [url] if url and not _is_generic(url) else []
        ok = await auto_cover(
            nid, page_urls=pages, wikidata_title=title if seed else None
        )
        print(f"{nid} {title}: {'cover set' if ok else 'no cover found'}")
        if ok:
            got[nid] = title
    return got


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--novel", type=int, default=None, help="only this novel id")
    args = ap.parse_args()
    init_engine()
    got = asyncio.run(fill_covers(args.novel))
    print(f"{len(got)} cover(s) added")


if __name__ == "__main__":
    main()
