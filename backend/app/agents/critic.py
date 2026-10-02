"""Critic agent: non-blocking QA flags for a candidate translation.

Deterministic checks run first (glossary drift with an automatic fix for known
variants, leftover CJK). One LLM pass then flags unknown names, pronouns and
idioms. Nothing here ever triggers a retranslation, and an LLM failure just
means fewer flags.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..common.logging import get_logger
from ..llm.client import LLMClient
from ..review.checks import deterministic_flags
from .prompts import CRITIC_SYSTEM, CRITIC_USER_TEMPLATE, CRITIC_VERSION

log = get_logger(__name__)

LLM_KINDS = {"unknown_name", "pronoun", "idiom"}

_CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "source_span": {"type": "string"},
                    "target_span": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        }
    },
    "required": ["flags"],
}


@dataclass
class CritiqueResult:
    ok: bool
    flags: list[dict] = field(default_factory=list)
    fixed_text: str = ""


def _clean_llm_flags(data) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("flags"), list):
        return []
    out = []
    for f in data["flags"]:
        if not isinstance(f, dict) or f.get("kind") not in LLM_KINDS:
            continue
        out.append({
            "kind": f["kind"],
            "source_span": str(f.get("source_span") or "")[:512],
            "target_span": str(f.get("target_span") or "")[:512],
            "note": str(f.get("note") or "")[:1000],
        })
    return out


async def critique_translation(
    *,
    source: str,
    candidate: str,
    glossary: list[tuple[str, str]],
    client: LLMClient,
    variants: dict[str, list[str]] | None = None,
) -> CritiqueResult:
    if not candidate.strip():
        return CritiqueResult(ok=False, flags=[], fixed_text=candidate)

    fixed, flags = deterministic_flags(source, candidate, glossary, variants or {})
    user = CRITIC_USER_TEMPLATE.format(source=source, candidate=fixed)
    try:
        data = await client.generate_json(
            user,
            system=CRITIC_SYSTEM,
            schema=_CRITIC_SCHEMA,
            temperature=0.0,
            max_output_tokens=2048,
        )
        flags = flags + _clean_llm_flags(data)
    except Exception as e:  # noqa: BLE001 - QA must never block a translation
        log.warning("critic.fail", err=str(e), version=CRITIC_VERSION)
    return CritiqueResult(ok=not flags, flags=flags, fixed_text=fixed)
