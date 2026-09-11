"""Translator agent.

For each paragraph:
  1. find glossary terms whose source_term appears in the paragraph
  2. call Gemini with the constrained glossary block
  3. parse new terms back out
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..common.logging import get_logger
from ..embed.gemini import GeminiClient, get_gemini
from .prompts import TRANSLATOR_SYSTEM, TRANSLATOR_USER_TEMPLATE, TRANSLATOR_VERSION

log = get_logger(__name__)


_TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "translation": {"type": "string"},
        "new_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_term": {"type": "string"},
                    "target_term": {"type": "string"},
                    "kind": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["source_term", "target_term"],
            },
        },
    },
    "required": ["translation"],
}


@dataclass
class TranslationResult:
    translation: str
    new_terms: list[dict]
    used_terms: list[tuple[str, str]]


def _format_glossary(rows: Iterable[tuple[str, str]]) -> str:
    rows = list(rows)
    if not rows:
        return "(no locked terms — translate naturally and propose new terms)"
    return "\n".join(f"- {s} -> {t}" for s, t in rows)


_PARA_SPLIT = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in _PARA_SPLIT.split(text) if p.strip()]


async def translate_paragraph(
    paragraph: str,
    *,
    glossary: list[tuple[str, str]],
    target_lang: str,
    chapter_idx: int,
    client: GeminiClient | None = None,
) -> TranslationResult:
    if not paragraph.strip():
        return TranslationResult(translation="", new_terms=[], used_terms=[])

    used = [(s, t) for s, t in glossary if s and s in paragraph]
    block = _format_glossary(used)

    user = TRANSLATOR_USER_TEMPLATE.format(
        target_lang=target_lang,
        glossary_block=block,
        paragraph=paragraph,
    )
    g = client or get_gemini()
    try:
        data = await g.generate_json(
            user,
            system=TRANSLATOR_SYSTEM,
            schema=_TRANSLATE_SCHEMA,
            temperature=0.2,
            max_output_tokens=4096,
        )
    except Exception as e:
        log.warning("translator.fail", chapter_idx=chapter_idx, err=str(e))
        return TranslationResult(translation="", new_terms=[], used_terms=used)

    if not isinstance(data, dict):
        return TranslationResult(translation="", new_terms=[], used_terms=used)
    translation = str(data.get("translation") or "").strip()
    new_terms = data.get("new_terms") or []
    coined: list[dict] = []
    for t in new_terms:
        if not isinstance(t, dict):
            continue
        src = (t.get("source_term") or "").strip()
        tgt = (t.get("target_term") or "").strip()
        if not src or not tgt:
            continue
        coined.append(
            {
                "source_term": src,
                "target_term": tgt,
                "kind": t.get("kind", "other"),
                "confidence": float(t.get("confidence", 0.5)),
                "first_chapter": chapter_idx,
                "version": TRANSLATOR_VERSION,
            }
        )
    return TranslationResult(
        translation=translation, new_terms=coined, used_terms=used
    )


async def translate_chapter(
    chapter_text: str,
    *,
    glossary: list[tuple[str, str]],
    target_lang: str,
    chapter_idx: int,
    client: GeminiClient | None = None,
) -> TranslationResult:
    paras = split_paragraphs(chapter_text)
    if not paras:
        return TranslationResult(translation="", new_terms=[], used_terms=[])

    pieces: list[str] = []
    all_new: list[dict] = []
    all_used: list[tuple[str, str]] = []
    for p in paras:
        r = await translate_paragraph(
            p,
            glossary=glossary,
            target_lang=target_lang,
            chapter_idx=chapter_idx,
            client=client,
        )
        pieces.append(r.translation)
        all_new.extend(r.new_terms)
        all_used.extend(r.used_terms)
        # Merge newly-coined into local glossary so later paragraphs reuse.
        for t in r.new_terms:
            pair = (t["source_term"], t["target_term"])
            if pair not in glossary:
                glossary.append(pair)
    log.info(
        "translator.chapter_done",
        chapter_idx=chapter_idx,
        new_terms=len(all_new),
        paragraphs=len(paras),
    )
    return TranslationResult(
        translation="\n\n".join(pieces),
        new_terms=all_new,
        used_terms=all_used,
    )
