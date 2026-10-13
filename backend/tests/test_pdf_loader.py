from pathlib import Path

import pytest

from app.ingest.pdf_loader import load_pdf

FIX = Path(__file__).parent / "fixtures"


def test_pdf_text_extracted():
    text = load_pdf(FIX / "two_pages.pdf")
    assert "Chapter One hello" in text and "Second page text" in text
    assert text.index("Chapter One") < text.index("Second page")
    assert "\n\n" in text


def test_empty_pdf_raises():
    with pytest.raises(ValueError, match="no extractable text"):
        load_pdf(FIX / "blank.pdf")


def test_corrupt_pdf_raises_value_error(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"not a pdf")
    with pytest.raises(ValueError):
        load_pdf(p)
