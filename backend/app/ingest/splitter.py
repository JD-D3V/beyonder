"""Chapter splitter.

Recognises common Chinese and English chapter headers, and falls back to
length-based splitting when a book has none, or when a section that a header
introduced turns out to be far bigger than any real chapter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedChapter:
    idx: int
    title: str | None
    text: str


# Match: 第123章 / 第一百二十三章 / 第123节
_ZH_CHAPTER_RE = re.compile(
    r"^\s*第[\d一二三四五六七八九十百千零〇两]+[章节回卷部篇][^\n]{0,80}$",
    re.MULTILINE,
)
# Match: Chapter 12 / Chapter 12: title / CHAPTER 12
_EN_CHAPTER_RE = re.compile(
    r"^\s*(?:Chapter|CHAPTER|Ch\.?)\s+\d+[^\n]{0,160}$",
    re.MULTILINE,
)

_FALLBACK_CHARS = 6000  # ~one web-novel chapter

# Past this, a "chapter" is really an unsplit book and gets broken up anyway.
_OVERSIZE_CHARS = _FALLBACK_CHARS * 2

_PARA_BREAK = "\n\n"


def _find_headers(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, title) for each header found."""
    hits: list[tuple[int, int, str]] = []
    for regex in (_ZH_CHAPTER_RE, _EN_CHAPTER_RE):
        for m in regex.finditer(text):
            hits.append((m.start(), m.end(), m.group(0).strip()))
    hits.sort(key=lambda h: h[0])
    return hits


def _part_title(title: str | None, part: int) -> str | None:
    if title is None:
        return None
    return title if part == 0 else f"{title} ({part + 1})"


def _units(text: str) -> list[str]:
    """Break text into the smallest pieces that are still safe to keep whole.

    Scraped pages rarely have blank lines between paragraphs: the extractor
    joins blocks with single newlines, so splitting on blank lines alone can
    leave the entire book as one indivisible unit. Fall through progressively
    finer boundaries, and only slice mid-sentence when there is nothing else.
    """
    units = [u for u in text.split(_PARA_BREAK) if u.strip()]

    for separator in ("\n", None):
        if all(len(u) <= _FALLBACK_CHARS for u in units):
            return units
        finer: list[str] = []
        for unit in units:
            if len(unit) <= _FALLBACK_CHARS:
                finer.append(unit)
            elif separator is not None:
                finer.extend(p for p in unit.split(separator) if p.strip())
            else:
                # Sentence ends, Chinese and Latin. Kept on the left so a piece
                # never starts with stray punctuation.
                finer.extend(
                    p for p in re.split(r"(?<=[。！？!?])\s*", unit) if p.strip()
                )
        units = finer

    # Nothing left to break on: one unbroken run of characters.
    out: list[str] = []
    for unit in units:
        if len(unit) <= _FALLBACK_CHARS:
            out.append(unit)
        else:
            out.extend(
                unit[i : i + _FALLBACK_CHARS]
                for i in range(0, len(unit), _FALLBACK_CHARS)
            )
    return out


def _split_by_length(text: str, title: str | None = None) -> list[ParsedChapter]:
    """Gather text into roughly chapter-sized pieces on safe boundaries."""
    out: list[ParsedChapter] = []
    buf: list[str] = []
    chars = 0

    def flush() -> None:
        nonlocal buf, chars
        if not buf:
            return
        out.append(
            ParsedChapter(
                idx=len(out),
                title=_part_title(title, len(out)),
                text=_PARA_BREAK.join(buf),
            )
        )
        buf = []
        chars = 0

    for unit in _units(text):
        buf.append(unit.strip())
        chars += len(unit)
        if chars >= _FALLBACK_CHARS:
            flush()
    flush()
    return out


def split_chapters(text: str) -> list[ParsedChapter]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    hits = _find_headers(text)
    if not hits:
        return _split_by_length(text)

    sections: list[tuple[str | None, str]] = []

    # Anything before the first header is a prologue when there is enough of it.
    if hits[0][0] > 200:
        prologue = text[: hits[0][0]].strip()
        if prologue:
            sections.append(("Prologue", prologue))

    for i, (_start, end, title) in enumerate(hits):
        next_start = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        body = text[end:next_start].strip()
        if body:
            sections.append((title, body))

    out: list[ParsedChapter] = []
    for title, body in sections:
        # A single stray header, say a volume marker at the top of a page that
        # holds many stories, used to leave the whole book as one chapter:
        # headers existed, so the length fallback never ran. Anything far past
        # a plausible chapter now gets broken up however it was found.
        pieces = (
            _split_by_length(body, title)
            if len(body) > _OVERSIZE_CHARS
            else [ParsedChapter(idx=0, title=title, text=body)]
        )
        for piece in pieces:
            out.append(
                ParsedChapter(idx=len(out), title=piece.title, text=piece.text)
            )
    return out
