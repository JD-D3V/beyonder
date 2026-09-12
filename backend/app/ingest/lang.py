"""Language detection for imported text.

Script beats statistics here. ``langdetect`` is trained on word shapes, and on
CJK it guesses badly and confidently: a page of Chinese web-novel prose comes
back as Korean often enough to matter, and the detected language decides which
prompt the translator uses.

So look at the writing system first, because that part is not a guess. Japanese
prose carries kana, Korean carries hangul, and text with Han characters and
neither of those is Chinese. Only when the script is inconclusive, which means
mostly-Latin text, is langdetect asked.
"""
from __future__ import annotations

import re

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_HIRA_RE = re.compile(r"[぀-ゟ]")
_KATA_RE = re.compile(r"[゠-ヿ]")
_HANGUL_RE = re.compile(r"[가-힯ᄀ-ᇿ]")

_LATIN_RE = re.compile(r"[A-Za-z]")

# A stray Han character in an English page is a quotation, not Chinese prose.
# One percent of a long sample is still dozens of characters, and the script
# must also out-weigh the Latin letters around it.
_MIN_SCRIPT_RATIO = 0.01


def _ratio(pattern: re.Pattern[str], sample: str) -> float:
    if not sample:
        return 0.0
    return len(pattern.findall(sample)) / len(sample)


def script_hint(text: str) -> str | None:
    """Language implied by the writing system, or None if it says nothing."""
    sample = "".join(text[:4000].split())
    if not sample:
        return None

    latin = _ratio(_LATIN_RE, sample)
    kana = _ratio(_HIRA_RE, sample) + _ratio(_KATA_RE, sample)
    hangul = _ratio(_HANGUL_RE, sample)
    han = _ratio(_CJK_RE, sample)

    for ratio, code in ((kana, "ja"), (hangul, "ko"), (han, "zh")):
        # Out-weighing Latin is what separates CJK prose from an English page
        # quoting a term like 渡劫.
        if ratio >= _MIN_SCRIPT_RATIO and ratio > latin:
            return code
    return None


def detect_lang(text: str) -> str:
    """Return an ISO-639-1 code: zh, ja, ko, en, and so on."""
    if not text or not text.strip():
        return "en"
    sample = text[:4000]

    hint = script_hint(sample)
    if hint is not None:
        return hint

    try:
        code = detect(sample)
    except LangDetectException:
        return "en"
    if code.startswith("zh"):
        return "zh"
    return code
