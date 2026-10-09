from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import ITEM_COVER, ITEM_DOCUMENT, ITEM_IMAGE, epub


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


def _find_cover(book: epub.EpubBook) -> bytes | None:
    """OPF ``<meta name="cover">``, then a cover-image item, then the first image."""
    try:
        for _, attrs in book.get_metadata("OPF", "cover"):
            item = book.get_item_with_id(attrs.get("content", ""))
            if item is not None and item.get_content():
                return item.get_content()
    except Exception:
        pass
    for kind in (ITEM_COVER, ITEM_IMAGE):
        for item in book.get_items_of_type(kind):
            if item.get_content():
                return item.get_content()
    return None


def load_epub_with_cover(path: str | Path) -> tuple[str, bytes | None]:
    """Like ``load_epub`` but also returns the raw cover image bytes, if any."""
    text = load_epub(path)
    try:
        cover = _find_cover(epub.read_epub(str(path)))
    except Exception:
        cover = None
    return text, cover
