"""End-to-end chapter -> chunks -> embeddings -> Qdrant pipeline."""
from __future__ import annotations

import asyncio
from typing import Sequence

from ..common.logging import get_logger
from ..ingest.chunker import chunk_text
from ..storage.models import Chapter
from . import local
from .qdrant import ensure_collection, upsert_chunks

log = get_logger(__name__)


async def embed_chapters(novel_id: int, chapters: Sequence[Chapter]) -> int:
    """Chunk + embed + upsert. Returns total point count."""
    if not chapters:
        return 0
    ensure_collection()
    total = 0
    for chap in chapters:
        chunks = chunk_text(
            chap.source_text, chapter_idx=chap.idx, chapter_id=chap.id
        )
        if not chunks:
            continue
        embs = await asyncio.to_thread(local.embed_texts, [c.text for c in chunks])
        n = upsert_chunks(novel_id=novel_id, chunks=chunks, embeddings=embs)
        total += n
        log.info(
            "embed.chapter_done",
            novel_id=novel_id,
            chapter_idx=chap.idx,
            chunks=n,
        )
    return total


async def embed_query(query: str) -> list[float]:
    vecs = await asyncio.to_thread(local.embed_texts, [query])
    return vecs[0]
