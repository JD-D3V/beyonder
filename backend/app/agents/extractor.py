"""Glossary extractor agent.

Reads a chapter, returns proposed glossary entries. Batched to respect the
Gemini RPM cap — call this per chapter, not per paragraph.
"""
from __future__ import annotations

from typing import Iterable

from ..common.logging import get_logger
from ..embed.gemini import GeminiClient, get_gemini
from .prompts import EXTRACTOR_SYSTEM, EXTRACTOR_USER_TEMPLATE, EXTRACTOR_VERSION

log = get_logger(__name__)


_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_term": {"type": "string"},
                    "target_term": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "character",
                            "sect",
                            "technique",
                            "realm",
                            "item",
                            "place",
                            "other",
                        ],
                    },
                    "confidence": {"type": "number"},
                    "notes": {"type": "string"},
                },
                "required": ["source_term", "target_term", "kind", "confidence"],
            },
        }
    },
    "required": ["terms"],
}


def _format_known(known: Iterable[tuple[str, str]]) -> str:
    rows = [f"- {s} -> {t}" for s, t in known]
    return "\n".join(rows) if rows else "(none yet)"


async def extract_terms_from_chapter(
    *,
    novel_title: str,
    source_lang: str,
    chapter_idx: int,
    chapter_text: str,
    known_terms: Iterable[tuple[str, str]] = (),
    client: GeminiClient | None = None,
    max_chars: int = 12000,
) -> list[dict]:
    """Return a list of dicts with source_term/target_term/kind/confidence/notes/first_chapter."""
    if not chapter_text.strip():
        return []
    body = chapter_text[:max_chars]
    user = EXTRACTOR_USER_TEMPLATE.format(
        chapter_idx=chapter_idx,
        novel_title=novel_title,
        source_lang=source_lang,
        known_terms=_format_known(known_terms),
        chapter_text=body,
    )
    g = client or get_gemini()
    try:
        data = await g.generate_json(
            user,
            system=EXTRACTOR_SYSTEM,
            schema=_EXTRACT_SCHEMA,
            temperature=0.1,
            max_output_tokens=4096,
        )
    except Exception as e:
        log.warning("extractor.fail", chapter_idx=chapter_idx, err=str(e))
        return []
    terms = data.get("terms", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for t in terms:
        if not isinstance(t, dict):
            continue
        src = (t.get("source_term") or "").strip()
        tgt = (t.get("target_term") or "").strip()
        if not src or not tgt:
            continue
        out.append(
            {
                "source_term": src,
                "target_term": tgt,
                "kind": t.get("kind", "other"),
                "confidence": float(t.get("confidence", 0.5)),
                "notes": t.get("notes"),
                "first_chapter": chapter_idx,
                "version": EXTRACTOR_VERSION,
            }
        )
    log.info("extractor.done", chapter_idx=chapter_idx, n=len(out))
    return out
