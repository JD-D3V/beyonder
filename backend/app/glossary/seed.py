"""Built-in xianxia glossary: standard English renderings for common terms.

Matched against chapter text before the LLM extractor runs, so cultivation
vocabulary is rendered consistently from the first chapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_SEED_PATH = Path(__file__).with_name("seed_xianxia.yaml")
SEED_CONFIDENCE = 0.9


@dataclass(frozen=True)
class SeedTerm:
    source: str
    target: str
    kind: str


@lru_cache(maxsize=1)
def load_seed() -> list[SeedTerm]:
    raw = yaml.safe_load(_SEED_PATH.read_text(encoding="utf-8")) or []
    return [SeedTerm(e["source"], e["target"], e.get("kind", "other")) for e in raw]


@lru_cache(maxsize=1)
def _by_length() -> list[SeedTerm]:
    return sorted(load_seed(), key=lambda t: len(t.source), reverse=True)


def match_seed(text: str, known_sources: set[str]) -> list[dict]:
    """Seed terms present in ``text``, longest match first, as extractor-shaped dicts.

    Matched spans are consumed, so 金丹期 wins over its substring 金丹 (but a
    separate bare 金丹 elsewhere in the text still matches). Sources in
    ``known_sources`` are skipped. ``first_chapter`` is left for the caller.
    """
    if not text:
        return []
    consumed = [False] * len(text)
    found: dict[str, SeedTerm] = {}
    for t in _by_length():
        start = 0
        while True:
            i = text.find(t.source, start)
            if i < 0:
                break
            end = i + len(t.source)
            start = i + 1
            if any(consumed[i:end]):
                continue
            for k in range(i, end):
                consumed[k] = True
            if t.source not in known_sources:
                found.setdefault(t.source, t)
    return [
        {
            "source_term": t.source,
            "target_term": t.target,
            "kind": t.kind,
            "confidence": SEED_CONFIDENCE,
            "notes": "seed",
        }
        for t in found.values()
    ]
