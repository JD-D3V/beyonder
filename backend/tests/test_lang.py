from app.ingest.lang import detect_lang


def test_lang_zh():
    assert detect_lang("王林站在山门前。") == "zh"


def test_lang_en():
    assert detect_lang("The quick brown fox jumps over the lazy dog.") == "en"


def test_lang_ja_heuristic():
    # Hiragana forces ja regardless of langdetect's guess
    assert detect_lang("こんにちは、私は学生です。") == "ja"
