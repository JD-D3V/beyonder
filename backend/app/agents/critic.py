"""Critic agent — flags glossary drift in a candidate translation.

We do a deterministic check first (fast, no token cost). The LLM is only used
to suggest a fix when deterministic violations are found.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..common.logging import get_logger
from ..embed.gemini import GeminiClient, get_gemini
from .prompts import CRITIC_SYSTEM, CRITIC_USER_TEMPLATE, CRITIC_VERSION

log = get_logger(__name__)


_CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_term": {"type": "string"},
                    "expected": {"type": "string"},
                    "found": {"type": "string"},
                },
            },
        },
        "suggested_fix": {"type": "string"},
    },
    "required": ["ok"],
}


@dataclass
class CritiqueResult:
    ok: bool
    violations: list[dict]
    suggested_fix: str


def _format_glossary(rows: Iterable[tuple[str, str]]) -> str:
    rows = list(rows)
    if not rows:
        return "(empty)"
    return "\n".join(f"- {s} -> {t}" for s, t in rows)


def _deterministic_violations(
    *, source: str, candidate: str, glossary: list[tuple[str, str]]
) -> list[dict]:
    """Fast offline check: term in source, expected target NOT in candidate."""
    out: list[dict] = []
    lower_candidate = candidate.lower()
    for src, tgt in glossary:
        if not src or not tgt:
            continue
        if src in source and tgt.lower() not in lower_candidate:
            out.append({"source_term": src, "expected": tgt, "found": ""})
    return out


async def critique_translation(
    *,
    source: str,
    candidate: str,
    glossary: list[tuple[str, str]],
    client: GeminiClient | None = None,
    use_llm_fix: bool = True,
) -> CritiqueResult:
    if not candidate.strip():
        return CritiqueResult(ok=False, violations=[], suggested_fix="")

    det = _deterministic_violations(
        source=source, candidate=candidate, glossary=glossary
    )
    if not det:
        return CritiqueResult(ok=True, violations=[], suggested_fix="")

    if not use_llm_fix:
        return CritiqueResult(ok=False, violations=det, suggested_fix="")

    user = CRITIC_USER_TEMPLATE.format(
        glossary_block=_format_glossary(glossary),
        source=source,
        candidate=candidate,
    )
    g = client or get_gemini()
    try:
        data = await g.generate_json(
            user,
            system=CRITIC_SYSTEM,
            schema=_CRITIC_SCHEMA,
            temperature=0.0,
            max_output_tokens=4096,
        )
    except Exception as e:
        log.warning("critic.fail", err=str(e), version=CRITIC_VERSION)
        return CritiqueResult(ok=False, violations=det, suggested_fix="")

    if not isinstance(data, dict):
        return CritiqueResult(ok=False, violations=det, suggested_fix="")
    return CritiqueResult(
        ok=bool(data.get("ok", False)),
        violations=data.get("violations") or det,
        suggested_fix=str(data.get("suggested_fix") or ""),
    )
