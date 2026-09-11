from __future__ import annotations

from pathlib import Path

import chardet


def load_txt(path: str | Path) -> str:
    """Robust text load — autodetect encoding (gbk/gb18030/utf-8 etc.)."""
    raw = Path(path).read_bytes()
    if not raw:
        return ""
    # Strip BOM if present
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    guess = chardet.detect(raw)
    enc = (guess.get("encoding") or "utf-8").lower()
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")
