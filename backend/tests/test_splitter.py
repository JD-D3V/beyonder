from app.ingest.splitter import split_chapters


def test_splitter_zh_chapters():
    text = "第一章 山门\n王林来到山门前。\n\n第二章 拜师\n王林见到张长老。"
    parts = split_chapters(text)
    assert len(parts) == 2
    assert "王林" in parts[0].text
    assert "第二章" not in parts[0].text


def test_splitter_en_chapters():
    text = "Chapter 1: Arrival\nHe arrived.\n\nChapter 2: Departure\nHe left."
    parts = split_chapters(text)
    assert len(parts) == 2
    assert "He arrived" in parts[0].text


def test_splitter_fallback_no_headers():
    body = "para. " * 5000
    parts = split_chapters(body)
    assert len(parts) >= 1
