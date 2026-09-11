"""Chapter splitter.

Recognises common Chinese and English chapter headers. Falls back to
length-based splitting if no headers are found.
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


def _find_headers(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, title) for each header found."""
    hits: list[tuple[int, int, str]] = []
    for regex in (_ZH_CHAPTER_RE, _EN_CHAPTER_RE):
        for m in regex.finditer(text):
            hits.append((m.start(), m.end(), m.group(0).strip()))
    hits.sort(key=lambda h: h[0])
    return hits


def split_chapters(text: str) -> list[ParsedChapter]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    hits = _find_headers(text)

    if hits:
        out: list[ParsedChapter] = []
        for i, (start, end, title) in enumerate(hits):
            next_start = hits[i + 1][0] if i + 1 < len(hits) else len(text)
            body = text[end:next_start].strip()
            if not body:
                continue
            out.append(ParsedChapter(idx=i, title=title, text=body))
        # Stuff before first header is treated as prologue if substantial
        if hits and hits[0][0] > 200:
            prologue = text[: hits[0][0]].strip()
            if prologue:
                out = [ParsedChapter(idx=0, title="Prologue", text=prologue)] + [
                    ParsedChapter(idx=c.idx + 1, title=c.title, text=c.text)
                    for c in out
                ]
        return out

    # Fallback: split by char count
    out = []
    paras = text.split("\n\n")
    buf: list[str] = []
    chars = 0
    idx = 0
    for p in paras:
        p = p.strip()
        if not p:
            continue
        buf.append(p)
        chars += len(p)
        if chars >= _FALLBACK_CHARS:
            out.append(ParsedChapter(idx=idx, title=None, text="\n\n".join(buf)))
            idx += 1
            buf = []
            chars = 0
    if buf:
        out.append(ParsedChapter(idx=idx, title=None, text="\n\n".join(buf)))
    return out
