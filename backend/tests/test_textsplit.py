from app.common.textsplit import pack_units, split_chunks, split_units

PARA = "段落文字。" * 40  # 200 characters


def test_blank_line_paragraphs_are_kept_whole():
    text = "\n\n".join([PARA] * 3)
    assert split_units(text, 1200) == [PARA] * 3


def test_single_newline_text_still_splits():
    # Scraped pages join blocks with single newlines. Splitting on blank lines
    # alone left the whole chapter as one indivisible unit, which then went to
    # the model in a single request and came back empty.
    text = "\n".join([PARA] * 30)
    units = split_units(text, 1200)
    assert len(units) > 1
    assert max(len(u) for u in units) <= 1200


def test_sentences_are_used_when_there_are_no_line_breaks():
    text = "这是一个句子。" * 300
    units = split_units(text, 1200)
    assert max(len(u) for u in units) <= 1200
    # Pieces end on sentence punctuation rather than mid-clause.
    assert all(u.endswith("。") for u in units)


def test_text_with_no_breaks_at_all_is_sliced():
    units = split_units("字" * 5000, 1200)
    assert len(units) == 5
    assert max(len(u) for u in units) == 1200


def test_nothing_is_lost():
    text = "\n".join([PARA] * 12)
    joined = "".join(split_units(text, 1000))
    assert len(joined) == len(text.replace("\n", ""))


def test_packing_reduces_request_count():
    # One request per piece against a per-minute rate limit: thirty short lines
    # translated separately is thirty times slower for no gain.
    units = ["短句。" * 10] * 30
    packed = pack_units(units, 1200)
    assert len(packed) < len(units)
    assert max(len(p) for p in packed) <= 1200


def test_split_chunks_fills_pieces():
    text = "\n".join([PARA] * 30)
    chunks = split_chunks(text, 1200)
    assert max(len(c) for c in chunks) <= 1200
    # Every piece except the last should be reasonably full.
    assert all(len(c) > 600 for c in chunks[:-1])


def test_empty_input():
    assert split_units("", 100) == []
    assert split_units("   ", 100) == []
    assert split_chunks("", 100) == []
