"""Rebuild the Qdrant collection with the local embedding model.

    python -m app.scripts.reembed [--novel ID]

With --novel, only that novel is re-embedded (collection is kept if its
dimension already matches). Without it, the collection is recreated and every
novel is re-embedded.
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from ..common.config import settings
from ..embed.pipeline import embed_chapters
from ..embed.qdrant import get_qdrant
from ..storage.db import get_session
from ..storage.models import Chapter, Novel


async def _run(novel_id: int | None) -> None:
    store = get_qdrant()
    if novel_id is None:
        try:
            store.client.delete_collection(store.collection)
        except Exception:
            pass
    with get_session() as db:
        q = select(Novel.id)
        if novel_id is not None:
            q = q.where(Novel.id == novel_id)
        for nid in db.scalars(q).all():
            chaps = db.scalars(
                select(Chapter).where(Chapter.novel_id == nid).order_by(Chapter.idx)
            ).all()
            n = await embed_chapters(nid, chaps)
            print(f"novel {nid}: {n} chunks (dim {settings.embedding_dim})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--novel", type=int, default=None)
    args = ap.parse_args()
    asyncio.run(_run(args.novel))


if __name__ == "__main__":
    main()
