"""Break text into pieces no larger than a limit, on the safest boundary.

Two callers need this and they used to disagree. The chapter splitter broke a
book into chapters, the translator broke a chapter into paragraphs, and both
split on blank lines only. Scraped pages join their blocks with single
newlines, so neither could divide such a page at all: the importer produced one
enormous chapter, and the translator then sent that whole chapter to the model
as a single request, which came back empty because the output cap is far
smaller than a chapter of Chinese prose.

The rule here is to keep the largest units that fit, and only descend to a
finer boundary for the pieces that are still too big.
"""
from __future__ import annotations

import re

_PARA_BREAK = re.compile(r"\n\s*\n")
_LINE_BREAK = re.compile(r"\n")
# Sentence ends, Chinese and Latin. The punctuation stays with the sentence it
# closes, so no piece begins with a stray mark.
_SENTENCE_END = re.compile(r"(?<=[。！？!?])\s*")


def split_units(text: str, max_chars: int) -> list[str]:
    """Split text into pieces of at most ``max_chars`` where the text allows.

    A piece can still exceed the limit only if it contains no break of any kind
    and slicing it would cut a word, which the final pass handles anyway.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    text = text.strip()
    if not text:
        return []

    units = [u.strip() for u in _PARA_BREAK.split(text) if u.strip()]

    for pattern in (_LINE_BREAK, _SENTENCE_END):
        if all(len(u) <= max_chars for u in units):
            return units
        finer: list[str] = []
        for unit in units:
            if len(unit) <= max_chars:
                finer.append(unit)
            else:
                finer.extend(p.strip() for p in pattern.split(unit) if p.strip())
        units = finer

    # Nothing left to break on: an unbroken run of characters.
    out: list[str] = []
    for unit in units:
        if len(unit) <= max_chars:
            out.append(unit)
        else:
            out.extend(
                unit[i : i + max_chars] for i in range(0, len(unit), max_chars)
            )
    return out


def pack_units(units: list[str], max_chars: int, joiner: str = "\n\n") -> list[str]:
    """Greedily recombine small units into pieces near ``max_chars``.

    Splitting alone can leave a chapter as dozens of single lines. Each piece
    costs one model request against a rate limit measured in requests per
    minute, so translating thirty short lines separately is thirty times slower
    than translating six full pieces, for no gain in quality.
    """
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for unit in units:
        addition = len(unit) + (len(joiner) if buf else 0)
        if buf and size + addition > max_chars:
            out.append(joiner.join(buf))
            buf, size = [], 0
            addition = len(unit)
        buf.append(unit)
        size += addition
    if buf:
        out.append(joiner.join(buf))
    return out


def split_chunks(text: str, max_chars: int, joiner: str = "\n\n") -> list[str]:
    """Split, then repack: pieces as close to ``max_chars`` as the text allows."""
    return pack_units(split_units(text, max_chars), max_chars, joiner)
