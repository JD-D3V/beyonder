import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.translator import translate_chapter


class FakeLLM:
    model_name = "fake-model"

    def __init__(self):
        self.prompts: list[str] = []

    async def generate(self, prompt, **kw):
        self.prompts.append(prompt)
        return "text"

    async def generate_json(self, prompt, *, schema, **kw):
        self.prompts.append(prompt)
        return {"translation": "Hello", "new_terms": []}


@pytest.mark.asyncio
async def test_translate_chapter_uses_given_client():
    llm = FakeLLM()
    r = await translate_chapter(
        "你好", glossary=[], target_lang="en", chapter_idx=0, client=llm
    )
    assert r.translation == "Hello"
    assert llm.prompts


@pytest.mark.asyncio
async def test_resumable_step_uses_given_client(monkeypatch):
    from app.graph import resumable

    saved = []

    class _S:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    chap = SimpleNamespace(source_text="你好", id=1)
    monkeypatch.setattr(resumable, "get_session", lambda: _S())
    monkeypatch.setattr(resumable, "get_chapter_by_idx", lambda s, n, i: chap)
    monkeypatch.setattr(resumable, "get_novel", lambda s, n: SimpleNamespace(title="T", title_en="x"))
    monkeypatch.setattr(resumable, "get_translation", lambda s, **k: None)
    monkeypatch.setattr(resumable, "get_terms_for_chapters", lambda *a, **k: [])
    monkeypatch.setattr(resumable, "upsert_terms", lambda *a, **k: None)
    monkeypatch.setattr(resumable, "insert_relations", lambda *a, **k: None)
    monkeypatch.setattr(
        resumable, "upsert_translation", lambda s, **k: saved.append(k)
    )
    llm = FakeLLM()
    res = await resumable.translate_step(llm=llm, novel_id=1, chapter_idx=0)
    assert res.complete
    assert llm.prompts
    assert saved and all(k["model"] == "fake-model" for k in saved)


def test_no_module_imports_google_generativeai():
    root = Path(__file__).resolve().parent.parent / "app"
    for p in root.rglob("*.py"):
        assert "google.generativeai" not in p.read_text(), p
