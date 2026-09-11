"""Token-aware recursive chunker.

Uses tiktoken's cl100k_base as a portable approximator. Gemini's tokenizer
isn't pip-installable, but cl100k counts are within ~10% for both English and
Chinese in practice — good enough for chunk sizing.
"""
from __future__ import annotations

from dataclasses import dataclass

import tiktoken

from ..common.config import settings


_ENC = tiktoken.get_encoding("cl100k_base")


@dataclass
class ChunkSpec:
    chapter_idx: int
    chapter_id: int | None
    char_start: int
    char_end: int
    text: str


def _count_tokens(text: str) -> int:
    return len(_ENC.encode(text, disallowed_special=()))


# Recursive separators — split at the biggest boundary that keeps us under
# the target. Order matters: paragraph -> sentence -> any.
_SEPS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]


def _hard_split_by_tokens(text: str, target: int) -> list[str]:
    """Last-resort: slice by token count, no separator needed."""
    ids = _ENC.encode(text, disallowed_special=())
    if not ids:
        return [text] if text else []
    out: list[str] = []
    step = max(1, target)
    for i in range(0, len(ids), step):
        piece = _ENC.decode(ids[i : i + step])
        if piece:
            out.append(piece)
    return out or [text]


def _split(text: str, target: int, sep_idx: int = 0) -> list[str]:
    """Recursive token-bounded split.

    We advance ``sep_idx`` on recursion so an oversize chunk falls through to
    finer separators instead of re-trying the same one (which would loop when
    a single sentence is already at the target boundary).
    """
    if _count_tokens(text) <= target:
        return [text]
    while sep_idx < len(_SEPS):
        sep = _SEPS[sep_idx]
        if sep == "":
            return _hard_split_by_tokens(text, target)
        if sep not in text:
            sep_idx += 1
            continue
        parts = text.split(sep)
        out: list[str] = []
        buf: list[str] = []
        buf_tok = 0
        for p in parts:
            p_tok = _count_tokens(p)
            if buf_tok + p_tok > target and buf:
                out.append(sep.join(buf))
                buf = [p]
                buf_tok = p_tok
            else:
                buf.append(p)
                buf_tok += p_tok
        if buf:
            out.append(sep.join(buf))
        final: list[str] = []
        for chunk in out:
            if _count_tokens(chunk) > target:
                final.extend(_split(chunk, target, sep_idx + 1))
            else:
                final.append(chunk)
        return final
    return _hard_split_by_tokens(text, target)


def chunk_text(
    text: str,
    *,
    chapter_idx: int,
    chapter_id: int | None = None,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[ChunkSpec]:
    """Split a chapter into overlapping token-bounded chunks."""
    if not text.strip():
        return []
    target = target_tokens or settings.chunk_target_tokens
    overlap = overlap_tokens or settings.chunk_overlap_tokens

    raw_chunks = _split(text, target)
    out: list[ChunkSpec] = []
    cursor = 0
    prev_tail = ""
    for i, c in enumerate(raw_chunks):
        text_with_overlap = (prev_tail + c) if prev_tail else c
        char_start = max(0, cursor - len(prev_tail))
        char_end = cursor + len(c)
        out.append(
            ChunkSpec(
                chapter_idx=chapter_idx,
                chapter_id=chapter_id,
                char_start=char_start,
                char_end=char_end,
                text=text_with_overlap.strip(),
            )
        )
        # Build overlap tail for next chunk
        ids = _ENC.encode(c, disallowed_special=())
        tail_ids = ids[-overlap:] if overlap > 0 else []
        prev_tail = _ENC.decode(tail_ids) if tail_ids else ""
        cursor += len(c)
    return out
