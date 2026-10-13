"""Rebuild the Qdrant collection with the local embedding model.

    python -m app.scripts.reembed [--novel ID]

The collection is recreated whenever its dimension is wrong. Without --novel
it is always recreated and every novel is re-embedded; with --novel only that
novel is re-embedded (other novels' vectors are dropped if the dim changed,
so rerun without --novel to restore them).
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
    if novel_id is None or store.existing_dim() not in (None, settings.embedding_dim):
        # collection_exists never raises for "not found"; real errors propagate.
        if store.client.collection_exists(store.collection):
            store.client.delete_collection(store.collection)
    store.ensure(settings.embedding_dim)
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
