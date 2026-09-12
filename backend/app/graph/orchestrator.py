"""LangGraph wiring for the translation pipeline.

Nodes:
    extract -> translate -> critic -> (retry translate) -> persist

Branching:
    after critic, if violations and retries left, loop back to translate with
    the critic's suggested_fix as a seed; otherwise persist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, StateGraph

from ..agents.critic import critique_translation
from ..agents.extractor import extract_terms_from_chapter
from ..agents.relation import extract_relations_from_chapter
from ..agents.translator import translate_chapter
from ..common.config import settings
from ..common.logging import get_logger
from ..embed.gemini import get_gemini
from ..storage.db import get_session
from ..storage.repository import (
    get_chapter_by_idx,
    get_terms_for_chapters,
    insert_relations,
    upsert_terms,
    upsert_translation,
)

log = get_logger(__name__)


@dataclass
class TranslateState:
    novel_id: int
    novel_title: str
    source_lang: str
    target_lang: str
    chapter_idx: int
    chapter_text: str = ""
    chapter_db_id: int | None = None

    # populated as we go
    glossary: list[tuple[str, str]] = field(default_factory=list)
    new_terms: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    translation: str = ""
    critic_passes: int = 0
    retries_left: int = settings.critic_max_retries
    done: bool = False
    error: str | None = None


# --- nodes ---------------------------------------------------------------

def _skip(state: TranslateState) -> dict[str, Any]:
    """A node that has nothing to do still has to write something.

    LangGraph rejects an empty update with "expected node X to update at least
    one of ...", which surfaced as a failed translation rather than a skipped
    step. Writing the error field back is a no-op that satisfies it.
    """
    return {"error": state.error}


async def node_load(state: TranslateState) -> dict[str, Any]:
    """Pull chapter text + existing glossary from Postgres."""
    with get_session() as s:
        chap = get_chapter_by_idx(s, state.novel_id, state.chapter_idx)
        if chap is None:
            return {"error": f"chapter {state.chapter_idx} not found", "done": True}
        terms = get_terms_for_chapters(
            s,
            state.novel_id,
            up_to_chapter=state.chapter_idx,
            target_lang=state.target_lang,
        )
        gloss = [(t.source_term, t.target_term) for t in terms]
    return {
        "chapter_text": chap.source_text,
        "chapter_db_id": chap.id,
        "glossary": gloss,
    }


async def node_extract(state: TranslateState) -> dict[str, Any]:
    if state.error or not state.chapter_text:
        return _skip(state)
    new_terms = await extract_terms_from_chapter(
        novel_title=state.novel_title,
        source_lang=state.source_lang,
        chapter_idx=state.chapter_idx,
        chapter_text=state.chapter_text,
        known_terms=state.glossary,
    )
    # Merge into glossary for the translator stage
    merged = list(state.glossary)
    for t in new_terms:
        pair = (t["source_term"], t["target_term"])
        if pair not in merged:
            merged.append(pair)
    return {"new_terms": new_terms, "glossary": merged}


async def node_translate(state: TranslateState) -> dict[str, Any]:
    if state.error or not state.chapter_text:
        return _skip(state)
    result = await translate_chapter(
        state.chapter_text,
        glossary=list(state.glossary),
        target_lang=state.target_lang,
        chapter_idx=state.chapter_idx,
    )
    merged_new = list(state.new_terms) + list(result.new_terms)
    merged_gloss = list(state.glossary)
    for t in result.new_terms:
        pair = (t["source_term"], t["target_term"])
        if pair not in merged_gloss:
            merged_gloss.append(pair)
    return {
        "translation": result.translation,
        "new_terms": merged_new,
        "glossary": merged_gloss,
    }


async def node_critic(state: TranslateState) -> dict[str, Any]:
    if state.error or not state.translation:
        return _skip(state)
    res = await critique_translation(
        source=state.chapter_text,
        candidate=state.translation,
        glossary=list(state.glossary),
    )
    out: dict[str, Any] = {"critic_passes": state.critic_passes + 1}
    if res.ok or state.retries_left <= 0:
        out["done"] = True
    else:
        if res.suggested_fix:
            out["translation"] = res.suggested_fix
        out["retries_left"] = state.retries_left - 1
        out["done"] = False
    return out


async def node_relations(state: TranslateState) -> dict[str, Any]:
    if state.error or not state.chapter_text:
        return _skip(state)
    entities = [s for s, _ in state.glossary]
    rels = await extract_relations_from_chapter(
        novel_title=state.novel_title,
        chapter_idx=state.chapter_idx,
        chapter_text=state.chapter_text,
        entities=entities,
    )
    return {"relations": rels}


async def node_persist(state: TranslateState) -> dict[str, Any]:
    if state.error:
        return _skip(state)
    with get_session() as s:
        if state.new_terms:
            # Re-fetch fresh: assign embeddings via separate flow if needed
            upsert_terms(
                s,
                novel_id=state.novel_id,
                entries=state.new_terms,
                target_lang=state.target_lang,
            )
        if state.relations:
            insert_relations(s, novel_id=state.novel_id, entries=state.relations)
        if state.translation and state.chapter_db_id is not None:
            upsert_translation(
                s,
                chapter_id=state.chapter_db_id,
                target_lang=state.target_lang,
                text=state.translation,
                model=get_gemini().model_name,
                critic_passes=state.critic_passes,
            )
    log.info(
        "graph.persist",
        novel_id=state.novel_id,
        chapter_idx=state.chapter_idx,
        critic_passes=state.critic_passes,
        new_terms=len(state.new_terms),
        relations=len(state.relations),
    )
    return {"done": True}


# --- graph ---------------------------------------------------------------

def _route_after_critic(state: TranslateState) -> str:
    return "persist" if state.done else "translate"


def build_translation_graph():
    g = StateGraph(TranslateState)
    g.add_node("load", node_load)
    g.add_node("extract", node_extract)
    g.add_node("translate", node_translate)
    g.add_node("critic", node_critic)
    g.add_node("relate", node_relations)
    g.add_node("persist", node_persist)

    g.set_entry_point("load")
    g.add_edge("load", "extract")
    g.add_edge("extract", "translate")
    g.add_edge("translate", "critic")
    g.add_conditional_edges(
        "critic",
        _route_after_critic,
        {"translate": "translate", "persist": "relate"},
    )
    g.add_edge("relate", "persist")
    g.add_edge("persist", END)
    return g.compile()


async def run_translation_graph(
    *,
    novel_id: int,
    novel_title: str,
    source_lang: str,
    target_lang: str,
    chapter_idx: int,
) -> TranslateState:
    graph = build_translation_graph()
    init = TranslateState(
        novel_id=novel_id,
        novel_title=novel_title,
        source_lang=source_lang,
        target_lang=target_lang,
        chapter_idx=chapter_idx,
    )
    final = await graph.ainvoke(init)
    # LangGraph returns a dict-like snapshot; merge it back into a dataclass.
    if isinstance(final, dict):
        out = TranslateState(
            novel_id=novel_id,
            novel_title=novel_title,
            source_lang=source_lang,
            target_lang=target_lang,
            chapter_idx=chapter_idx,
        )
        for k, v in final.items():
            if hasattr(out, k):
                setattr(out, k, v)
        return out
    return final  # type: ignore[return-value]
