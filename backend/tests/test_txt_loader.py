from pathlib import Path

from app.ingest.txt_loader import load_txt

# Original throwaway lines, not from any real book.
CJK = "第一章 山門\n\n少年抬頭望向山門，石階上落滿了雨。"


def _write(tmp_path: Path, data: bytes, name: str = "n.txt") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_utf8_is_never_guessed_at(tmp_path: Path):
    # Short CJK samples get confidently misdetected. Valid UTF-8 must win, or
    # characters silently become replacement marks and flow into translation.
    p = _write(tmp_path, CJK.encode("utf-8"))
    assert load_txt(p) == CJK


def test_utf8_bom_is_stripped(tmp_path: Path):
    p = _write(tmp_path, b"\xef\xbb\xbf" + CJK.encode("utf-8"))
    out = load_txt(p)
    assert out == CJK
    assert not out.startswith("\ufeff")


def test_gb18030_source(tmp_path: Path):
    p = _write(tmp_path, CJK.encode("gb18030"))
    assert load_txt(p) == CJK


def test_big5_source(tmp_path: Path):
    p = _write(tmp_path, CJK.encode("big5"))
    assert load_txt(p) == CJK


def test_utf16_source(tmp_path: Path):
    p = _write(tmp_path, CJK.encode("utf-16"))
    assert load_txt(p) == CJK


def test_empty_file(tmp_path: Path):
    assert load_txt(_write(tmp_path, b"")) == ""


def test_no_replacement_characters_survive(tmp_path: Path):
    for encoding in ("utf-8", "gb18030", "big5"):
        p = _write(tmp_path, CJK.encode(encoding), f"{encoding}.txt")
        assert "\ufffd" not in load_txt(p)


# A bare chapter header is the shortest thing a real import contains, and short
# CJK samples are exactly where statistical detection fails: chardet calls this
# one koi8-r with 0.68 confidence, and decoding through that mangles every
# character. Scoring the candidate decodes is what catches it.
SHORT_HEADER = "第一章 山門"


def test_short_gbk_header_survives(tmp_path: Path):
    p = _write(tmp_path, SHORT_HEADER.encode("gb18030"))
    assert load_txt(p) == SHORT_HEADER


def test_short_big5_header_survives(tmp_path: Path):
    # The mirror case: picking GBK for everything would break Taiwanese files.
    p = _write(tmp_path, SHORT_HEADER.encode("big5"))
    assert load_txt(p) == SHORT_HEADER


def test_ascii_is_untouched(tmp_path: Path):
    plain = "Chapter 1" + chr(10) * 2 + "The gate stood open."
    p = _write(tmp_path, plain.encode("utf-8"))
    assert load_txt(p) == plain
