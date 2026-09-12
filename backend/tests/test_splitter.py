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


def test_oversized_section_is_split_even_though_a_header_matched():
    # A page of many short stories under one volume marker used to arrive as a
    # single enormous chapter: a header existed, so the length fallback never
    # ran. Real imports hit this, and a 40k-character "chapter" is unusable.
    para = "段落文字。" * 200
    text = "第01卷\n\n" + ("\n\n".join([para] * 20))
    parts = split_chapters(text)
    assert len(parts) > 1
    assert all(len(p.text) < 8000 for p in parts)
    assert [p.idx for p in parts] == list(range(len(parts)))


def test_oversized_split_keeps_the_header_title_on_the_parts():
    para = "段落文字。" * 200
    text = "第01卷\n\n" + ("\n\n".join([para] * 20))
    parts = split_chapters(text)
    assert parts[0].title == "第01卷"
    # Later pieces stay attributable to the section they came from.
    assert all("第01卷" in (p.title or "") for p in parts)


def test_normal_chapters_are_not_resplit():
    body = "句子。" * 40
    text = f"第一章 山門\n\n{body}\n\n第二章 試劍\n\n{body}"
    parts = split_chapters(text)
    assert len(parts) == 2
    assert parts[0].title == "第一章 山門"
    assert parts[1].title == "第二章 試劍"


def test_scraped_text_without_blank_lines_still_splits():
    # Page extractors join blocks with single newlines, so a scraped book can
    # contain no blank lines at all. Splitting only on blank lines left the
    # whole thing as one indivisible unit.
    body = "\n".join("段落文字。" * 40 for _ in range(180))
    parts = split_chapters("第01卷\n" + body)
    assert len(parts) > 1
    assert max(len(p.text) for p in parts) < 8000


def test_text_with_no_breaks_at_all_still_splits():
    parts = split_chapters("字" * 30000)
    assert len(parts) > 1
    assert max(len(p.text) for p in parts) <= 6000
