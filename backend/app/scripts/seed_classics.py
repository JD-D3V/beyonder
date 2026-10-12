"""Seed the catalog with public-domain Chinese classics from Wikisource.

    python -m app.scripts.seed_classics [--works xiyouji,fengshen,...] [--max-chapters 30]

Creates public, completed, ownerless novels; skips titles that already exist.
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from ..common.logging import get_logger
from ..embed.pipeline import embed_chapters
from ..ingest.wikisource import SOURCE_NOTE, WORKS, Work, WikisourceClient
from ..storage.db import get_session
from ..storage.models import Chapter, Novel
from ..storage.repository import create_novel, insert_chapter, update_novel

log = get_logger(__name__)


async def seed_work(client: WikisourceClient, work: Work, max_chapters: int) -> int | None:
    """Create one novel; returns its id, or None when it already exists."""
    with get_session() as s:
        if s.scalar(select(Novel.id).where(Novel.title == work.title)) is not None:
            print(f"{work.title}: already present, skipped")
            return None
    pages = (await client.chapter_pages(work))[:max_chapters]
    if not pages:
        print(f"{work.title}: no chapter pages found")
        return None
    chapters = []
    for page in pages:
        ch = await client.chapter(page)
        if ch.text.strip():
            chapters.append(ch)
        else:
            log.warning("seed.empty_chapter", page=page)
    if not chapters:
        print(f"{work.title}: no chapter text fetched")
        return None
    with get_session() as s:
        novel = create_novel(
            s, title=work.title, source_lang="zh",
            source_url=f"https://zh.wikisource.org/wiki/{work.toc_page}".replace(" ", "_"),
            visibility="public", owner_id=None,
        )
        update_novel(
            s, novel.id, author=work.author,
            description=f"{work.description}\n\n{SOURCE_NOTE}",
            tags=",".join(work.tags), status="completed",
        )
        for i, ch in enumerate(chapters):
            insert_chapter(
                s, novel_id=novel.id, idx=i, title=ch.title, source_text=ch.text,
                source_url=f"https://zh.wikisource.org/wiki/{ch.page}".replace(" ", "_")[:1024],
            )
        novel_id = novel.id
    with get_session() as s:
        chaps = list(
            s.scalars(
                select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.idx)
            ).all()
        )
        s.expunge_all()
    try:
        await embed_chapters(novel_id, chaps)
    except Exception as e:  # noqa: BLE001 - chapters are saved; `make reembed` can retry
        print(f"{work.title}: embedding failed ({e}); run make reembed")
    print(f"{work.title}: novel {novel_id}, {len(chapters)} chapters")
    for i, ch in enumerate(chapters):
        print(f"  {i}: {ch.title}")
    return novel_id


async def seed(keys: list[str], max_chapters: int, client: WikisourceClient | None = None) -> list[int]:
    own = client is None
    client = client or WikisourceClient()
    ids: list[int] = []
    try:
        for key in keys:
            nid = await seed_work(client, WORKS[key], max_chapters)
            if nid is not None:
                ids.append(nid)
    finally:
        if own:
            await client.aclose()
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--works", default=",".join(WORKS), help=f"comma list of: {', '.join(WORKS)}")
    ap.add_argument("--max-chapters", type=int, default=30)
    args = ap.parse_args()
    keys = [k.strip() for k in args.works.split(",") if k.strip()]
    unknown = [k for k in keys if k not in WORKS]
    if unknown:
        ap.error(f"unknown works: {', '.join(unknown)}")
    asyncio.run(seed(keys, max(1, args.max_chapters)))


if __name__ == "__main__":
    main()
