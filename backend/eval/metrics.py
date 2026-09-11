"""Eval metrics.

Q&A
---
- accuracy: fraction of non-spoiler rows where ANY ``gold_answer_contains``
  string appears in the answer (case-insensitive).
- spoiler_leakage: fraction of spoiler-probe rows where the model answered
  WITHOUT producing a refusal phrase. Lower is better.
- citation_accuracy: of rows with ``must_cite_chapter``, fraction where it
  appears in citations.

Translation
-----------
- term_consistency: for each (source_term, expected_target), fraction of
  chapters where the source appears and the expected_target also appears in
  the candidate translation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


def _contains_any(text: str, substrings: Iterable[str]) -> bool:
    t = text.lower()
    for s in substrings:
        if s and s.lower() in t:
            return True
    return False


@dataclass
class QARowResult:
    question: str
    answer: str
    correct: bool
    leaked: bool
    citation_ok: bool | None
    is_spoiler_probe: bool


@dataclass
class QASummary:
    n: int
    n_normal: int
    n_spoiler: int
    accuracy: float
    spoiler_leakage: float
    citation_accuracy: float

    @classmethod
    def from_rows(cls, rows: Sequence[QARowResult]) -> "QASummary":
        n = len(rows)
        normal = [r for r in rows if not r.is_spoiler_probe]
        spoiler = [r for r in rows if r.is_spoiler_probe]
        n_normal = len(normal)
        n_spoiler = len(spoiler)
        acc = sum(1 for r in normal if r.correct) / n_normal if n_normal else 0.0
        leak = (
            sum(1 for r in spoiler if r.leaked) / n_spoiler if n_spoiler else 0.0
        )
        cit_rows = [r for r in rows if r.citation_ok is not None]
        cit = (
            sum(1 for r in cit_rows if r.citation_ok) / len(cit_rows)
            if cit_rows
            else 0.0
        )
        return cls(
            n=n,
            n_normal=n_normal,
            n_spoiler=n_spoiler,
            accuracy=acc,
            spoiler_leakage=leak,
            citation_accuracy=cit,
        )


def score_qa(
    *,
    answer: str,
    gold_contains: Iterable[str],
    is_spoiler_probe: bool,
) -> tuple[bool, bool]:
    """Return (correct, leaked).

    For normal rows: correct iff answer contains any gold substring.
    For spoiler probes: leaked iff answer does NOT contain a refusal phrase
    listed in gold_contains.
    """
    hit = _contains_any(answer, gold_contains)
    if is_spoiler_probe:
        # Refusal phrases live in gold_contains. If hit, model refused -> no leak.
        return (True, not hit)
    return (hit, False)


@dataclass
class TermScore:
    source_term: str
    expected_target: str
    appearances: int
    consistent: int

    @property
    def rate(self) -> float:
        return self.consistent / self.appearances if self.appearances else 0.0


def score_term_consistency(
    *,
    source_term: str,
    expected_target: str,
    samples: Sequence[tuple[str, str]],
) -> TermScore:
    """``samples`` = list of (source_chunk, candidate_translation) pairs.

    A sample counts toward ``appearances`` if source_chunk contains
    source_term, and toward ``consistent`` if the candidate translation also
    contains expected_target (case-insensitive)."""
    appearances = 0
    consistent = 0
    et = expected_target.lower()
    for src, cand in samples:
        if source_term in src:
            appearances += 1
            if et in cand.lower():
                consistent += 1
    return TermScore(
        source_term=source_term,
        expected_target=expected_target,
        appearances=appearances,
        consistent=consistent,
    )
