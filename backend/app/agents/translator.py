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
from ..common.textsplit import split_chunks
from ..llm.client import LLMClient, LLMError
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


# One model request per piece, against a 4096 token output cap. Chinese
# expands when translated, so a piece of roughly this many characters leaves
# comfortable headroom. Scraped chapters arrive as a single unbroken block, and
# sending one of those whole returned nothing: the reply could not fit.
_MAX_TRANSLATION_CHARS = 1200


def split_paragraphs(text: str) -> list[str]:
    """Translation-sized pieces, never one unbroken chapter."""
    return split_chunks(text, _MAX_TRANSLATION_CHARS)


async def translate_paragraph(
    paragraph: str,
    *,
    glossary: list[tuple[str, str]],
    target_lang: str,
    chapter_idx: int,
    client: LLMClient,
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
    try:
        data = await client.generate_json(
            user,
            system=TRANSLATOR_SYSTEM,
            schema=_TRANSLATE_SCHEMA,
            temperature=0.2,
            max_output_tokens=4096,
        )
    except LLMError:
        # Key, quota or outage: the caller must see it (400/429/502). Swallowing
        # it here once stored blank "translations" in the shared library.
        raise
    except Exception as e:  # noqa: BLE001 - unexpected shape; caller decides
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
    client: LLMClient,
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
        if p.strip() and not r.translation.strip():
            # Never join blanks into a "complete" chapter.
            raise LLMError(
                "llm_upstream",
                "the model returned an empty translation for part of the chapter",
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


# --- titles ---------------------------------------------------------------

_TITLE_SYSTEM = (
    "You translate web-novel chapter and book titles. Reply with the translated "
    "title only: one line, plain text, no quotation marks, no commentary. Keep "
    "chapter numbering in the form 'Chapter 1: Title' (for example "
    "'第一章 青云山下' becomes 'Chapter 1: Below Azure Cloud Mountain'). Use the "
    "locked glossary renderings for any term they cover."
)

_QUOTES = "\"'`“”‘’「」『』"


def _clean_title(raw: object) -> str:
    """One line, no wrapping quotes, whitespace collapsed."""
    text = " ".join(str(raw or "").split())
    return text.strip(_QUOTES + " ").strip()


def _title_glossary(titles: Iterable[str], glossary: list[tuple[str, str]]) -> str:
    joined = "\n".join(titles)
    return _format_glossary([(s, t) for s, t in glossary if s and s in joined])


async def translate_title(
    client: LLMClient,
    title: str,
    glossary: list[tuple[str, str]],
    target_lang: str = "en",
) -> str:
    """Translate one title with the glossary. "" when the model gave nothing.

    LLMError propagates like every other agent call; anything else is logged
    and reported as an empty string so the caller leaves the title unset.
    """
    prompt = (
        f"Target language: {target_lang}.\n"
        f"Locked glossary (use exactly):\n{_title_glossary([title], glossary)}\n\n"
        f"Title:\n{title}"
    )
    try:
        raw = await client.generate(
            prompt, system=_TITLE_SYSTEM, temperature=0.2, max_output_tokens=200
        )
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("translator.title_fail", err=str(e))
        return ""
    return _clean_title(raw)


_TITLES_SCHEMA = {"type": "array", "items": {"type": "string"}}


async def translate_titles_batch(
    client: LLMClient,
    titles: list[str],
    glossary: list[tuple[str, str]],
    target_lang: str = "en",
) -> list[str | None]:
    """Translate many titles in one call. Aligned with ``titles``; None where
    the reply did not line up (wrong length) or an entry was blank."""
    if not titles:
        return []
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    prompt = (
        f"Target language: {target_lang}.\n"
        f"Locked glossary (use exactly):\n{_title_glossary(titles, glossary)}\n\n"
        f"Translate each of these {len(titles)} titles. Reply with a JSON array of "
        f"exactly {len(titles)} strings, in the same order.\n{numbered}"
    )
    try:
        data = await client.generate_json(
            prompt, system=_TITLE_SYSTEM, schema=_TITLES_SCHEMA,
            temperature=0.2, max_output_tokens=4096,
        )
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("translator.titles_fail", err=str(e))
        return [None] * len(titles)
    if not isinstance(data, list) or len(data) != len(titles):
        return [None] * len(titles)
    return [_clean_title(x) or None for x in data]
