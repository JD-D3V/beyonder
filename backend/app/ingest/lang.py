"""Language detection — falls back to zh/en/ja heuristic when langdetect fails
(short snippets, or content that confuses it)."""
from __future__ import annotations

import re

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0

_CJK_RE = re.compile(r"[一-鿿]")
_HIRA_RE = re.compile(r"[぀-ゟ]")
_KATA_RE = re.compile(r"[゠-ヿ]")
_HANGUL_RE = re.compile(r"[가-힯]")


def _heuristic(text: str) -> str:
    sample = text[:2000]
    if _HIRA_RE.search(sample) or _KATA_RE.search(sample):
        return "ja"
    if _HANGUL_RE.search(sample):
        return "ko"
    if _CJK_RE.search(sample):
        return "zh"
    return "en"


def detect_lang(text: str) -> str:
    """Return ISO-639-1 code: zh, en, ja, ko, etc."""
    if not text or not text.strip():
        return "en"
    sample = text[:4000]
    try:
        code = detect(sample)
        if code.startswith("zh"):
            return "zh"
        return code
    except LangDetectException:
        return _heuristic(sample)
