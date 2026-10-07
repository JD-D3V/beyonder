from app.ingest.splitter import split_chapters


def _body(n: int) -> str:
    return "\n\n".join(f"Paragraph {i}. " + "word " * 100 for i in range(n))


def test_header_section_up_to_book_size_stays_one_chapter():
    body = _body(100)
    assert 20_000 < len(body) < 60_000
    out = split_chapters("Chapter 1: Start\n\n" + body)
    assert len(out) == 1
    assert out[0].title == "Chapter 1: Start"


def test_header_section_over_book_size_is_split():
    body = _body(300)
    assert len(body) > 60_000
    out = split_chapters("Chapter 1: Start\n\n" + body)
    assert len(out) > 1
    assert out[1].title == "Chapter 1: Start (2)"


def test_unheaded_text_still_splits_by_length():
    out = split_chapters(_body(60))
    assert len(out) > 1
