"""Qdrant store for chapter chunks.

Payload shape (one point per chunk):
    {
      "novel_id": int,
      "chapter_id": int,
      "chapter_idx": int,
      "char_start": int,
      "char_end": int,
      "text": str,
    }
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence
import hashlib

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from ..common.config import settings
from ..common.logging import get_logger
from ..ingest.chunker import ChunkSpec

log = get_logger(__name__)


@dataclass
class SearchHit:
    score: float
    novel_id: int
    chapter_id: int
    chapter_idx: int
    char_start: int
    char_end: int
    text: str


class QdrantStore:
    def __init__(self, client: QdrantClient, collection: str) -> None:
        self.client = client
        self.collection = collection

    def ensure(self, dim: int) -> None:
        try:
            self.client.get_collection(self.collection)
            return
        except Exception:
            pass
        log.info("qdrant.create_collection", name=self.collection, dim=dim)
        self.client.recreate_collection(
            collection_name=self.collection,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            optimizers_config=qm.OptimizersConfigDiff(default_segment_number=2),
        )
        # Indexed payload fields for fast filtering
        for field, schema in (
            ("novel_id", qm.PayloadSchemaType.INTEGER),
            ("chapter_idx", qm.PayloadSchemaType.INTEGER),
        ):
            try:
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=schema,
                )
            except Exception:
                pass


@lru_cache(maxsize=1)
def get_qdrant() -> QdrantStore:
    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=30.0,
    )
    return QdrantStore(client, settings.qdrant_collection)


def ensure_collection(dim: int | None = None) -> None:
    get_qdrant().ensure(dim or settings.embedding_dim)


def _point_id(novel_id: int, chapter_id: int, char_start: int) -> int:
    h = hashlib.blake2b(
        f"{novel_id}:{chapter_id}:{char_start}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(h, "big") & 0x7FFFFFFFFFFFFFFF


def upsert_chunks(
    *,
    novel_id: int,
    chunks: Sequence[ChunkSpec],
    embeddings: Sequence[Sequence[float]],
) -> int:
    if not chunks:
        return 0
    if len(chunks) != len(embeddings):
        raise ValueError("chunks/embeddings length mismatch")
    store = get_qdrant()
    points = [
        qm.PointStruct(
            id=_point_id(novel_id, c.chapter_id or 0, c.char_start),
            vector=list(emb),
            payload={
                "novel_id": novel_id,
                "chapter_id": c.chapter_id,
                "chapter_idx": c.chapter_idx,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "text": c.text,
            },
        )
        for c, emb in zip(chunks, embeddings)
    ]
    store.client.upsert(collection_name=store.collection, points=points)
    return len(points)


def search_chunks(
    *,
    query_vec: Sequence[float],
    novel_id: int,
    max_chapter_idx: int | None = None,
    top_k: int = 8,
) -> list[SearchHit]:
    """Spoiler-aware search. Filter on novel_id + chapter_idx <= max."""
    store = get_qdrant()
    must: list[qm.FieldCondition] = [
        qm.FieldCondition(
            key="novel_id",
            match=qm.MatchValue(value=novel_id),
        )
    ]
    if max_chapter_idx is not None:
        must.append(
            qm.FieldCondition(
                key="chapter_idx",
                range=qm.Range(lte=float(max_chapter_idx)),
            )
        )
    flt = qm.Filter(must=must)
    res = store.client.search(
        collection_name=store.collection,
        query_vector=list(query_vec),
        query_filter=flt,
        limit=top_k,
        with_payload=True,
    )
    out: list[SearchHit] = []
    for r in res:
        p = r.payload or {}
        out.append(
            SearchHit(
                score=float(r.score),
                novel_id=int(p.get("novel_id", 0)),
                chapter_id=int(p.get("chapter_id") or 0),
                chapter_idx=int(p.get("chapter_idx", 0)),
                char_start=int(p.get("char_start", 0)),
                char_end=int(p.get("char_end", 0)),
                text=str(p.get("text", "")),
            )
        )
    return out
