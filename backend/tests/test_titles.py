import pytest

from app.agents.translator import translate_title, translate_titles_batch
from app.llm.client import LLMError


class FakeLLM:
    model_name = "fake-model"

    def __init__(self, reply="Chapter 1: Below Azure Cloud Mountain", json_reply=None):
        self.reply = reply
        self.json_reply = json_reply
        self.prompts: list[str] = []

    async def generate(self, prompt, **kw):
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    async def generate_json(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.json_reply


@pytest.mark.asyncio
async def test_title_prompt_carries_matching_glossary():
    llm = FakeLLM()
    out = await translate_title(
        llm, "第一章 青云山下", [("青云山", "Azure Cloud Mountain"), ("无关", "Unrelated")]
    )
    assert out == "Chapter 1: Below Azure Cloud Mountain"
    assert "青云山 -> Azure Cloud Mountain" in llm.prompts[0]
    assert "Unrelated" not in llm.prompts[0]
    assert "第一章 青云山下" in llm.prompts[0]


@pytest.mark.asyncio
async def test_title_strips_quotes_and_newlines():
    llm = FakeLLM(reply='\n  "Chapter 2: Trial\nof Swords"  \n')
    out = await translate_title(llm, "第二章 试剑", [])
    assert out == "Chapter 2: Trial of Swords"
    llm = FakeLLM(reply="“Chapter 3: Dawn”")
    assert await translate_title(llm, "第三章", []) == "Chapter 3: Dawn"


@pytest.mark.asyncio
async def test_title_llm_error_propagates_other_errors_return_empty():
    with pytest.raises(LLMError):
        await translate_title(FakeLLM(reply=LLMError("llm_upstream", "x")), "第一章", [])
    assert await translate_title(FakeLLM(reply=ValueError("odd")), "第一章", []) == ""


@pytest.mark.asyncio
async def test_batch_titles_returns_aligned_list():
    llm = FakeLLM(json_reply=["Chapter 1: A", '"Chapter 2: B"'])
    out = await translate_titles_batch(llm, ["第一章 甲", "第二章 乙"], [])
    assert out == ["Chapter 1: A", "Chapter 2: B"]


@pytest.mark.asyncio
async def test_batch_titles_wrong_shape_gives_none():
    llm = FakeLLM(json_reply=["only one"])
    out = await translate_titles_batch(llm, ["a", "b"], [])
    assert out == [None, None]
