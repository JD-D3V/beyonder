from app.ingest.lang import detect_lang


def test_lang_zh():
    assert detect_lang("王林站在山门前。") == "zh"


def test_lang_en():
    assert detect_lang("The quick brown fox jumps over the lazy dog.") == "en"


def test_lang_ja_heuristic():
    # Hiragana forces ja regardless of langdetect's guess
    assert detect_lang("こんにちは、私は学生です。") == "ja"


# langdetect is trained on word shapes and guesses badly on CJK: it called the
# first of these Korean. The detected language picks the translator prompt, so
# a confident wrong answer is worse than no answer. Script evidence decides.

def test_traditional_chinese_prose_is_not_korean():
    text = "少年抬頭望向山門，石階上落滿了雨。守山人問他來意，他只說要學劍。"
    assert detect_lang(text) == "zh"


def test_short_chapter_header():
    assert detect_lang("第一章 山門") == "zh"


def test_korean_is_still_korean():
    assert detect_lang("제1장 산문. 소년은 하늘을 올려다보았다.") == "ko"


def test_english_quoting_a_chinese_term_stays_english():
    # Two Han characters in a Latin sentence is a quotation, not Chinese prose.
    text = "The term 渡劫 appears in many cultivation novels and is hard to translate."
    assert detect_lang(text) == "en"


def test_chinese_prose_with_a_latin_name_stays_chinese():
    assert detect_lang("林軒說：Hello。他又說，今天天氣很好，適合練劍。") == "zh"


def test_empty_text():
    assert detect_lang("") == "en"
    assert detect_lang("   ") == "en"
