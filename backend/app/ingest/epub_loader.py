from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub


def load_epub(path: str | Path) -> str:
    """Extract plain text from an .epub. Preserves chapter order."""
    book = epub.read_epub(str(path))
    parts: list[str] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        try:
            html = item.get_content().decode("utf-8", errors="replace")
        except Exception:
            continue
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        if text:
            parts.append(text)
    return "\n\n".join(parts)
