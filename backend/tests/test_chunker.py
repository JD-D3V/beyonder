from app.ingest.chunker import chunk_text


def test_chunker_short_text_one_chunk():
    out = chunk_text("Hello world.", chapter_idx=0, chapter_id=1, target_tokens=500)
    assert len(out) == 1
    assert out[0].text.startswith("Hello")


def test_chunker_long_text_multiple_chunks():
    text = ("一二三四五六七八九十。" * 1000)
    out = chunk_text(text, chapter_idx=0, chapter_id=1, target_tokens=200, overlap_tokens=20)
    assert len(out) > 1
    # All chunks under ~200 tokens (~ rough char proxy)
    for c in out:
        assert len(c.text) < 4000


def test_chunker_metadata():
    out = chunk_text("para1\n\npara2\n\npara3", chapter_idx=5, chapter_id=42)
    assert all(c.chapter_idx == 5 for c in out)
    assert all(c.chapter_id == 42 for c in out)
