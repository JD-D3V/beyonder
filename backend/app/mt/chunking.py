"""Split text into provider-sized pieces on paragraph boundaries."""
from __future__ import annotations

import re

_SENT_END = re.compile(r"(?<=[。！？!?；;.])")


def _pieces(block: str, limit: int) -> list[str]:
    """Split one over-long paragraph on sentence ends, hard-cutting if needed."""
    if len(block) <= limit:
        return [block]
    parts: list[str] = []
    acc = ""
    for sent in _SENT_END.split(block):
        while len(sent) > limit:  # no punctuation at all: hard cut
            if acc:
                parts.append(acc)
                acc = ""
            parts.append(sent[:limit])
            sent = sent[limit:]
        if acc and len(acc) + len(sent) > limit:
            parts.append(acc)
            acc = ""
        acc += sent
    if acc:
        parts.append(acc)
    return parts


def chunk_text(text: str, limit: int = 4500) -> list[str]:
    """Pieces of at most ``limit`` chars; ``"".join`` of the result is ``text``.

    Packs whole paragraphs together, splits an over-long paragraph on sentence
    ends, and only hard-cuts a run with neither.
    """
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    cur = ""
    for para in text.splitlines(keepends=True):
        for piece in _pieces(para, limit):
            if cur and len(cur) + len(piece) > limit:
                out.append(cur)
                cur = ""
            cur += piece
    if cur:
        out.append(cur)
    return out
