"""LangGraph wiring for the translation pipeline.

Nodes:
    seed -> extract -> translate -> critic -> relate -> persist

The critic is non-blocking: it fixes known glossary drift, records review
flags, and never sends the chapter back for retranslation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, StateGraph
from langchain_core.runnables import RunnableConfig

from ..agents.critic import critique_translation
from ..agents.extractor import extract_terms_from_chapter
from ..agents.relation import extract_relations_from_chapter
from ..agents.translator import translate_chapter
from ..common.logging import get_logger
from ..glossary.seed import match_seed
from ..llm.client import LLMClient, LLMError
from ..storage.db import get_session
from ..storage.repository import (
    get_chapter_by_idx,
    get_terms_for_chapters,
    insert_relations,
    insert_seed_terms,
    load_variants,
    replace_open_flags,
    term_dicts,
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
    flags: list[dict] = field(default_factory=list)
    variants: dict[str, list[str]] = field(default_factory=dict)
    done: bool = False
    error: str | None = None
    # Set when a complete translation appeared meanwhile and we did not overwrite.
    lost_race: bool = False


# --- nodes ---------------------------------------------------------------

def _llm(config: RunnableConfig) -> LLMClient:
    return config["configurable"]["llm"]


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
        variants = load_variants(s, state.novel_id)
    return {
        "chapter_text": chap.source_text,
        "chapter_db_id": chap.id,
        "glossary": gloss,
        "variants": variants,
    }


async def node_seed(state: TranslateState, config: RunnableConfig) -> dict[str, Any]:
    """Add built-in xianxia terms found in the chapter that the glossary lacks."""
    if state.error or not state.chapter_text:
        return _skip(state)
    known = {src for src, _ in state.glossary}
    hits = match_seed(state.chapter_text, known)
    if not hits:
        return _skip(state)
    added_by = config["configurable"].get("translated_by")
    for h in hits:
        h["first_chapter"] = state.chapter_idx
        h["added_by"] = added_by
        h["_seed"] = True
    merged = list(state.glossary) + [
        (h["source_term"], h["target_term"]) for h in hits
    ]
    return {"new_terms": list(state.new_terms) + hits, "glossary": merged}


async def node_extract(state: TranslateState, config: RunnableConfig) -> dict[str, Any]:
    if state.error or not state.chapter_text:
        return _skip(state)
    new_terms = await extract_terms_from_chapter(
        client=_llm(config),
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
    return {"new_terms": list(state.new_terms) + new_terms, "glossary": merged}


async def node_translate(state: TranslateState, config: RunnableConfig) -> dict[str, Any]:
    if state.error or not state.chapter_text:
        return _skip(state)
    result = await translate_chapter(
        state.chapter_text,
        client=_llm(config),
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


async def node_critic(state: TranslateState, config: RunnableConfig) -> dict[str, Any]:
    if state.error or not state.translation:
        return _skip(state)
    res = await critique_translation(
        client=_llm(config),
        source=state.chapter_text,
        candidate=state.translation,
        glossary=list(state.glossary),
        variants=state.variants,
    )
    return {
        "critic_passes": state.critic_passes + 1,
        "translation": res.fixed_text or state.translation,
        "flags": res.flags,
        "done": True,
    }


async def node_relations(state: TranslateState, config: RunnableConfig) -> dict[str, Any]:
    if state.error or not state.chapter_text:
        return _skip(state)
    entities = [s for s, _ in state.glossary]
    rels = await extract_relations_from_chapter(
        client=_llm(config),
        novel_title=state.novel_title,
        chapter_idx=state.chapter_idx,
        chapter_text=state.chapter_text,
        entities=entities,
    )
    return {"relations": rels}


async def node_persist(state: TranslateState, config: RunnableConfig) -> dict[str, Any]:
    if state.error:
        return _skip(state)
    if state.chapter_text.strip() and not state.translation.strip():
        # Backstop: a blank result for a non-empty chapter is a model failure,
        # never something to save (it would be served as "complete").
        raise LLMError("llm_upstream", "the model returned an empty translation")
    wrote = True
    persisted: list[dict] = []
    with get_session() as s:
        if state.new_terms:
            added_by = config["configurable"].get("translated_by")
            for t in state.new_terms:
                t.setdefault("added_by", added_by)
            seed_hits = [t for t in state.new_terms if t.get("_seed")]
            others = [t for t in state.new_terms if not t.get("_seed")]
            created: list = []
            if seed_hits:
                # Seed hits only fill gaps; they never modify an existing row.
                created += insert_seed_terms(
                    s, novel_id=state.novel_id, entries=seed_hits,
                    target_lang=state.target_lang,
                )
            if others:
                upsert_terms(
                    s, novel_id=state.novel_id, entries=others,
                    target_lang=state.target_lang, created_out=created,
                )
            persisted = term_dicts(created)
        if state.relations:
            insert_relations(s, novel_id=state.novel_id, entries=state.relations)
        if state.translation and state.chapter_db_id is not None:
            wrote = upsert_translation(
                s,
                chapter_id=state.chapter_db_id,
                target_lang=state.target_lang,
                text=state.translation,
                model=_llm(config).model_name,
                critic_passes=state.critic_passes,
                translated_by=config["configurable"].get("translated_by"),
                overwrite=bool(config["configurable"].get("overwrite", False)),
            )
            if wrote:
                replace_open_flags(
                    s, state.novel_id, state.chapter_idx, state.flags
                )
    log.info(
        "graph.persist",
        novel_id=state.novel_id,
        chapter_idx=state.chapter_idx,
        critic_passes=state.critic_passes,
        new_terms=len(state.new_terms),
        relations=len(state.relations),
    )
    out: dict[str, Any] = {"done": True, "lost_race": wrote is False}
    if state.new_terms:
        # Report only rows created by this call (they carry ids).
        out["new_terms"] = persisted
    return out


# --- graph ---------------------------------------------------------------

def build_translation_graph():
    g = StateGraph(TranslateState)
    g.add_node("load", node_load)
    g.add_node("seed", node_seed)
    g.add_node("extract", node_extract)
    g.add_node("translate", node_translate)
    g.add_node("critic", node_critic)
    g.add_node("relate", node_relations)
    g.add_node("persist", node_persist)

    g.set_entry_point("load")
    g.add_edge("load", "seed")
    g.add_edge("seed", "extract")
    g.add_edge("extract", "translate")
    g.add_edge("translate", "critic")
    g.add_edge("critic", "relate")
    g.add_edge("relate", "persist")
    g.add_edge("persist", END)
    return g.compile()


async def run_translation_graph(
    *,
    llm: LLMClient,
    novel_id: int,
    novel_title: str,
    source_lang: str,
    target_lang: str,
    chapter_idx: int,
    translated_by: int | None = None,
    overwrite: bool = False,
) -> TranslateState:
    graph = build_translation_graph()
    init = TranslateState(
        novel_id=novel_id,
        novel_title=novel_title,
        source_lang=source_lang,
        target_lang=target_lang,
        chapter_idx=chapter_idx,
    )
    final = await graph.ainvoke(init, config={"configurable": {"llm": llm, "translated_by": translated_by, "overwrite": overwrite}})
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
