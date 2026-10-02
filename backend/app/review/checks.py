"""Deterministic QA checks. No LLM, no I/O."""
from __future__ import annotations

import re

# CJK ideographs, kana, hangul. Punctuation (U+3000 block) is excluded on purpose.
_CJK_RUN = re.compile(
    "[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]{2,}"
)


def untranslated_spans(text: str) -> list[str]:
    """Runs of at least two CJK characters left in the output."""
    return _CJK_RUN.findall(text or "")


def drift_violations(
    *, source: str, candidate: str, glossary: list[tuple[str, str]]
) -> list[dict]:
    """Term in source, locked target NOT in candidate (case-insensitive)."""
    out: list[dict] = []
    lower = candidate.lower()
    for src, tgt in glossary:
        if not src or not tgt:
            continue
        if src in source and tgt.lower() not in lower:
            out.append({"source_term": src, "expected": tgt, "found": ""})
    return out


def fix_glossary_drift(
    source: str,
    candidate: str,
    glossary: list[tuple[str, str]],
    variants: dict[str, list[str]],
) -> tuple[str, list[dict]]:
    """Replace known wrong renderings with the locked target; flag the rest."""
    flags: list[dict] = []
    for v in drift_violations(source=source, candidate=candidate, glossary=glossary):
        src, tgt = v["source_term"], v["expected"]
        hit = next((w for w in variants.get(src, []) if w and w in candidate), None)
        if hit is not None:
            candidate = candidate.replace(hit, tgt)
            continue
        flags.append({
            "kind": "glossary_drift",
            "source_span": src,
            "target_span": "",
            "note": f"expected '{tgt}'",
        })
    return candidate, flags


def deterministic_flags(
    source: str,
    candidate: str,
    glossary: list[tuple[str, str]],
    variants: dict[str, list[str]],
) -> tuple[str, list[dict]]:
    """Drift fix plus untranslated spans. Returns (fixed_text, flags)."""
    fixed, flags = fix_glossary_drift(source, candidate, glossary, variants)
    for span in untranslated_spans(fixed):
        flags.append({
            "kind": "untranslated", "source_span": "", "target_span": span, "note": "",
        })
    return fixed, flags
