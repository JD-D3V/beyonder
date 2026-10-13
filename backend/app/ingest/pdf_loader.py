"""Extract text from a PDF (text-layer only; no OCR)."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def load_pdf(path: str | Path) -> str:
    """Pages joined with a blank line. Raises ValueError if nothing extractable."""
    try:
        reader = PdfReader(str(path))
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
    except Exception as e:  # corrupt, encrypted, truncated ...
        raise ValueError(f"could not read PDF: {e}") from e
    text = "\n\n".join(p for p in pages if p)
    if not text.strip():
        raise ValueError("PDF has no extractable text (scanned?)")
    return text
