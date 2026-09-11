"""KG relation extractor — runs alongside the glossary extractor.

Kept separate so the term extractor stays small and the eval harness can
ablate the two independently.
"""
from __future__ import annotations

from typing import Iterable

from ..common.logging import get_logger
from ..embed.gemini import GeminiClient, get_gemini
from .prompts import RELATION_SYSTEM, RELATION_USER_TEMPLATE, RELATION_VERSION

log = get_logger(__name__)


_REL_SCHEMA = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "relation": {"type": "string"},
                    "dst": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["src", "relation", "dst"],
            },
        }
    },
    "required": ["relations"],
}


def _format_entities(entities: Iterable[str]) -> str:
    rows = [f"- {e}" for e in entities if e]
    return "\n".join(rows) if rows else "(none)"


async def extract_relations_from_chapter(
    *,
    novel_title: str,
    chapter_idx: int,
    chapter_text: str,
    entities: Iterable[str],
    client: GeminiClient | None = None,
    max_chars: int = 12000,
) -> list[dict]:
    if not chapter_text.strip():
        return []
    body = chapter_text[:max_chars]
    user = RELATION_USER_TEMPLATE.format(
        chapter_idx=chapter_idx,
        novel_title=novel_title,
        entities_block=_format_entities(entities),
        chapter_text=body,
    )
    g = client or get_gemini()
    try:
        data = await g.generate_json(
            user,
            system=RELATION_SYSTEM,
            schema=_REL_SCHEMA,
            temperature=0.1,
            max_output_tokens=4096,
        )
    except Exception as e:
        log.warning(
            "relation.fail",
            chapter_idx=chapter_idx,
            err=str(e),
            version=RELATION_VERSION,
        )
        return []
    rels = data.get("relations", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for r in rels:
        if not isinstance(r, dict):
            continue
        src = (r.get("src") or "").strip()
        dst = (r.get("dst") or "").strip()
        rel = (r.get("relation") or "").strip()
        if not (src and dst and rel):
            continue
        out.append(
            {
                "src": src,
                "dst": dst,
                "relation": rel,
                "first_chapter": chapter_idx,
                "confidence": float(r.get("confidence", 0.5)),
            }
        )
    log.info(
        "relation.done",
        chapter_idx=chapter_idx,
        n=len(out),
        version=RELATION_VERSION,
    )
    return out
