"""Knowledge-graph query helpers.

Returns nodes + edges shaped for D3 force-graph. Filters by spoiler chapter.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..storage.repository import get_relations, get_terms_for_chapters


@dataclass
class NodeOut:
    id: str
    label: str
    kind: str
    first_chapter: int


@dataclass
class EdgeOut:
    src: str
    dst: str
    relation: str
    first_chapter: int


def build_subgraph(
    session: Session,
    *,
    novel_id: int,
    up_to_chapter: int,
    target_lang: str = "en",
) -> tuple[list[NodeOut], list[EdgeOut]]:
    terms = get_terms_for_chapters(
        session, novel_id, up_to_chapter=up_to_chapter, target_lang=target_lang
    )
    rels = get_relations(session, novel_id, up_to_chapter=up_to_chapter)

    nodes_by_src: dict[str, NodeOut] = {}
    for t in terms:
        if t.kind in {"realm"}:  # realms render but aren't always linked
            kind = t.kind
        else:
            kind = t.kind
        nodes_by_src[t.source_term] = NodeOut(
            id=t.source_term,
            label=f"{t.target_term} ({t.source_term})",
            kind=kind,
            first_chapter=t.first_chapter,
        )

    edges: list[EdgeOut] = []
    for r in rels:
        # Auto-add unknown endpoints so the graph isn't sparse on first chapter.
        for endpoint in (r.src_term, r.dst_term):
            if endpoint not in nodes_by_src:
                nodes_by_src[endpoint] = NodeOut(
                    id=endpoint,
                    label=endpoint,
                    kind="other",
                    first_chapter=r.first_chapter,
                )
        edges.append(
            EdgeOut(
                src=r.src_term,
                dst=r.dst_term,
                relation=r.relation,
                first_chapter=r.first_chapter,
            )
        )
    return list(nodes_by_src.values()), edges
