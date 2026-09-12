"""Decode uploaded text files.

Web-novel text arrives in whatever encoding the source used: UTF-8 from most
modern sites, GBK/GB18030 from older Chinese ones, Big5 from Taiwanese ones.

Order matters. Statistical detection is a guess, and on short CJK samples it is
often a confident wrong guess, so try a strict UTF-8 decode first: if the bytes
are valid UTF-8 they are UTF-8, no guessing needed. Detection is only consulted
after that, and every attempt is strict, because a lossy decode turns real
characters into replacement marks that then flow silently into translation.
"""
from __future__ import annotations

import codecs
from pathlib import Path

import chardet

# Candidates tried when the bytes are not UTF-8. Strictness alone cannot pick
# between these: Big5 will happily decode GBK bytes into real but wrong
# characters, so every successful decode is scored and the best one wins.
_CANDIDATES = ("gb18030", "big5", "shift_jis", "euc-kr", "utf-16", "latin-1")

_MIN_DETECT_CONFIDENCE = 0.80

# A decode that produces these is almost certainly the right one. Two dozen of
# the most frequent Chinese characters plus the punctuation novels are full of;
# a wrong decode lands on rare characters and scores near zero.
_COMMON = set(
    "的一是不了在人有我他这中大来上国个到说们为子和你地出道时年得就那要下"
    "以生会自着过天而能对里去之下看起用发少年手心里門门山水火风雨"
    "，。！？、；：“”‘’《》…—"
)

# CJK Unified Ideographs, the extension A block, and CJK punctuation.
_CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F))


def _try(raw: bytes, encoding: str) -> str | None:
    """Decode strictly, or give up. A lossy decode is worse than no decode."""
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _score(text: str) -> float:
    """How much does this decode look like real CJK or Latin prose?

    Common characters count heavily, ordinary CJK and ASCII count a little, and
    control or private-use characters count against: those are the fingerprint
    of reading bytes through the wrong table.
    """
    if not text:
        return 0.0
    score = 0
    for ch in text:
        cp = ord(ch)
        if ch in _COMMON:
            score += 6
        elif _is_cjk(ch):
            score += 1
        elif ch.isascii() and (ch.isprintable() or ch.isspace()):
            score += 1
        elif 0xE000 <= cp <= 0xF8FF or cp == 0xFFFD:  # private use, replacement
            score -= 10
        elif not ch.isprintable() and not ch.isspace():
            score -= 10
    return score / len(text)


def load_txt(path: str | Path) -> str:
    """Read a text file, decoding it without corrupting characters."""
    raw = Path(path).read_bytes()
    if not raw:
        return ""

    if raw.startswith(codecs.BOM_UTF8):
        raw = raw[3:]
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        decoded = _try(raw, "utf-16")
        if decoded is not None:
            return decoded

    # Valid UTF-8 is UTF-8. No guessing, no scoring.
    decoded = _try(raw, "utf-8")
    if decoded is not None:
        return decoded

    candidates: list[tuple[float, int, str]] = []

    guess = chardet.detect(raw)
    enc = (guess.get("encoding") or "").lower()
    confidence = guess.get("confidence") or 0.0
    # A confident detection is trusted outright; chardet is good on any sample
    # long enough to have statistics. Short ones are where it invents Russian.
    if enc and confidence >= _MIN_DETECT_CONFIDENCE:
        decoded = _try(raw, enc)
        if decoded is not None:
            return decoded

    for rank, candidate in enumerate(_CANDIDATES):
        decoded = _try(raw, candidate)
        if decoded is not None:
            # Negative rank keeps the declared order as the tie-break.
            candidates.append((_score(decoded), -rank, decoded))

    if candidates:
        return max(candidates)[2]

    return raw.decode("utf-8", errors="replace")
