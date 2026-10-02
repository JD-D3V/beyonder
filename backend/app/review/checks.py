"""Deterministic QA checks. No LLM, no I/O."""
from __future__ import annotations

import re

# CJK ideographs, kana, hangul. Punctuation (U+3000 block) is excluded on purpose.
_CJK_RUN = re.compile(
    "[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]{2,}"
)


# Bracketed text is an intentional source annotation, e.g. "Qi (气)".
_BRACKETED = re.compile(r"\([^()]*\)|（[^（）]*）|\[[^\[\]]*\]")


def untranslated_spans(text: str) -> list[str]:
    """Distinct runs of at least two CJK characters left in the output.

    Runs inside (), （） or [] are skipped; duplicates are reported once.
    """
    cleaned = _BRACKETED.sub(" ", text or "")
    return list(dict.fromkeys(_CJK_RUN.findall(cleaned)))


def _variant_re(variant: str) -> re.Pattern[str]:
    pat = re.escape(variant)
    if re.match(r"\w", variant):
        pat = r"\b" + pat
    if re.search(r"\w$", variant):
        pat += r"\b"
    return re.compile(pat, re.IGNORECASE)


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
    for pair in glossary:
        # Recomputed per term against the current text, so earlier
        # replacements never leave a stale result behind.
        found = drift_violations(source=source, candidate=candidate, glossary=[pair])
        if not found:
            continue
        src, tgt = found[0]["source_term"], found[0]["expected"]
        for w in variants.get(src, []):
            if not w:
                continue
            rx = _variant_re(w)
            if rx.search(candidate):
                candidate = rx.sub(lambda _m, t=tgt: t, candidate)
                break
        else:
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
