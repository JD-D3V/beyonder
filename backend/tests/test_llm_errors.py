"""LLM failures must surface as LLMError (400/429/502), never as a blank
translation stored in the shared library."""
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.critic import critique_translation
from app.agents.extractor import extract_terms_from_chapter
from app.agents.relation import extract_relations_from_chapter
from app.agents.translator import translate_chapter, translate_paragraph
from app.auth.deps import current_user, current_user_optional
from app.llm.client import LLMClient, LLMError
from app.main import app


class _RaiseLLM:
    model_name = "fake"

    def __init__(self, code="llm_key_invalid"):
        self.code = code
        self.calls = 0

    async def generate(self, *a, **k):
        self.calls += 1
        raise LLMError(self.code, "nope")

    async def generate_json(self, *a, **k):
        self.calls += 1
        raise LLMError(self.code, "nope")


# --- client --------------------------------------------------------------


async def test_generate_json_unparseable_is_llm_upstream():
    tr = httpx.MockTransport(
        lambda r: httpx.Response(
            200, json={"choices": [{"message": {"content": "not json at all"}}]}
        )
    )
    c = LLMClient("groq", "k", transport=tr)
    with pytest.raises(LLMError) as ei:
        await c.generate_json("p", schema={"type": "object"})
    assert ei.value.code == "llm_upstream"


# --- agents re-raise -----------------------------------------------------


@pytest.mark.parametrize("code", ["llm_key_invalid", "llm_rate_limited", "llm_upstream"])
async def test_translate_paragraph_reraises(code):
    with pytest.raises(LLMError) as ei:
        await translate_paragraph(
            "你好", glossary=[], target_lang="en", chapter_idx=0, client=_RaiseLLM(code)
        )
    assert ei.value.code == code


async def test_extractor_reraises():
    with pytest.raises(LLMError):
        await extract_terms_from_chapter(
            novel_title="t", source_lang="zh", chapter_idx=0,
            chapter_text="你好", client=_RaiseLLM(),
        )


async def test_relation_reraises():
    with pytest.raises(LLMError):
        await extract_relations_from_chapter(
            novel_title="t", chapter_idx=0, chapter_text="你好",
            entities=[], client=_RaiseLLM(),
        )


async def test_critic_reraises():
    with pytest.raises(LLMError):
        await critique_translation(
            source="你好", candidate="Hello", glossary=[], client=_RaiseLLM()
        )


class _ParseFailLLM:
    model_name = "p"

    async def generate_json(self, *a, **k):
        return ["not", "a", "dict"]


async def test_extractor_relation_still_tolerate_bad_shapes():
    assert await extract_terms_from_chapter(
        novel_title="t", source_lang="zh", chapter_idx=0,
        chapter_text="你好", client=_ParseFailLLM(),
    ) == []
    assert await extract_relations_from_chapter(
        novel_title="t", chapter_idx=0, chapter_text="你好",
        entities=[], client=_ParseFailLLM(),
    ) == []


class _SecondEmptyLLM:
    model_name = "e"

    def __init__(self):
        self.n = 0

    async def generate_json(self, *a, **k):
        self.n += 1
        return {"translation": "ok" if self.n == 1 else "", "new_terms": []}


async def test_translate_chapter_raises_on_empty_piece():
    text = "甲" * 1000 + "\n\n" + "乙" * 1000
    with pytest.raises(LLMError) as ei:
        await translate_chapter(
            text, glossary=[], target_lang="en", chapter_idx=0, client=_SecondEmptyLLM()
        )
    assert ei.value.code == "llm_upstream"


# --- the real graph ------------------------------------------------------


@contextmanager
def _fake_session():
    yield object()


def _stub_graph_db(monkeypatch, writes):
    from app.graph import orchestrator as o

    chap = SimpleNamespace(id=5, source_text="王林来了。他很高兴。", title=None)
    monkeypatch.setattr(o, "get_session", _fake_session)
    monkeypatch.setattr(o, "get_novel", lambda s, n: SimpleNamespace(title_en="x"))
    monkeypatch.setattr(o, "get_chapter_by_idx", lambda s, n, i: chap)
    monkeypatch.setattr(o, "get_terms_for_chapters", lambda *a, **k: [])
    monkeypatch.setattr(o, "load_variants", lambda *a, **k: {})
    for name in (
        "upsert_translation", "upsert_terms", "insert_seed_terms",
        "insert_relations", "replace_open_flags",
    ):
        monkeypatch.setattr(
            o, name, lambda *a, _n=name, **k: writes.append(_n) or []
        )


def _key_invalid_client():
    tr = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad"}))
    return LLMClient("groq", "bad-key", transport=tr)


async def test_real_graph_with_invalid_key_raises_and_persists_nothing(monkeypatch):
    from app.graph.orchestrator import run_translation_graph

    writes: list[str] = []
    _stub_graph_db(monkeypatch, writes)
    with pytest.raises(LLMError) as ei:
        await run_translation_graph(
            llm=_key_invalid_client(), novel_id=1, novel_title="T",
            source_lang="zh", target_lang="en", chapter_idx=0,
        )
    assert ei.value.code == "llm_key_invalid"
    assert writes == []


class _BlankTranslatorLLM:
    """Extractor/critic/relations fine; translation always blank."""

    model_name = "b"

    async def generate_json(self, prompt, *, schema, **k):
        props = schema.get("properties", {})
        if "translation" in props:
            return {"translation": "", "new_terms": []}
        if "terms" in props:
            return {"terms": []}
        if "flags" in props:
            return {"flags": []}
        return {"relations": []}


async def test_real_graph_blank_translation_never_persisted(monkeypatch):
    from app.graph.orchestrator import run_translation_graph

    writes: list[str] = []
    _stub_graph_db(monkeypatch, writes)
    with pytest.raises(LLMError):
        await run_translation_graph(
            llm=_BlankTranslatorLLM(), novel_id=1, novel_title="T",
            source_lang="zh", target_lang="en", chapter_idx=0,
        )
    assert "upsert_translation" not in writes


async def test_node_persist_refuses_blank_translation(monkeypatch):
    from app.graph import orchestrator as o

    writes: list[str] = []
    _stub_graph_db(monkeypatch, writes)
    st = o.TranslateState(
        novel_id=1, novel_title="n", source_lang="zh", target_lang="en",
        chapter_idx=0, chapter_text="你好", chapter_db_id=5, translation="\n\n  ",
    )
    with pytest.raises(LLMError):
        await o.node_persist(st, {"configurable": {"llm": _RaiseLLM()}})
    assert writes == []


def test_translate_route_invalid_key_400_nothing_persisted(monkeypatch):
    writes: list[str] = []
    _stub_graph_db(monkeypatch, writes)
    monkeypatch.setattr("app.api.translate.get_session", _fake_session)
    monkeypatch.setattr(
        "app.api.translate.get_novel",
        lambda s, nid: SimpleNamespace(id=1, title="T", source_lang="zh"),
    )
    monkeypatch.setattr("app.api.translate.get_chapter_by_idx", lambda s, n, i: None)
    monkeypatch.setattr(
        "app.api.translate.resolve_llm", lambda h, u: _key_invalid_client()
    )
    user = SimpleNamespace(id=7, email="u@x", is_admin=False)
    app.dependency_overrides[current_user] = lambda: user
    try:
        with TestClient(app) as c:
            r = c.post("/translate", json={"novel_id": 1, "chapter_idx": 0})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "llm_key_invalid"
    assert writes == []


# --- resumable step ------------------------------------------------------


def _stub_step_db(monkeypatch, saved):
    from app.graph import resumable

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
    return resumable


@pytest.mark.parametrize("code", ["llm_key_invalid", "llm_rate_limited"])
async def test_translate_step_propagates_llm_error(monkeypatch, code):
    saved: list = []
    resumable = _stub_step_db(monkeypatch, saved)
    with pytest.raises(LLMError) as ei:
        await resumable.translate_step(llm=_RaiseLLM(code), novel_id=1, chapter_idx=0)
    assert ei.value.code == code
    assert saved == []


async def test_translate_step_blank_output_still_stalls(monkeypatch):
    saved: list = []
    resumable = _stub_step_db(monkeypatch, saved)
    res = await resumable.translate_step(
        llm=_BlankTranslatorLLM(), novel_id=1, chapter_idx=0
    )
    assert res.stalled and not res.complete
    assert saved == []


# --- upsert backstop -----------------------------------------------------


class _NoDB:
    def execute(self, *a, **k):
        raise AssertionError("must refuse before touching the database")


def test_upsert_translation_refuses_blank_complete():
    from app.storage.repository import upsert_translation

    with pytest.raises(ValueError):
        upsert_translation(
            _NoDB(), chapter_id=1, target_lang="en", text="  \n\n ",
            model="m", critic_passes=0,
        )


def test_upsert_translation_blank_complete_allowed_for_empty_source():
    """An empty chapter legitimately has an empty complete translation."""
    from app.storage.repository import upsert_translation

    with pytest.raises(AssertionError):  # reaches the DB: not refused
        upsert_translation(
            _NoDB(), chapter_id=1, target_lang="en", text="",
            model="m", critic_passes=0, allow_empty=True,
        )


# --- /ask ----------------------------------------------------------------


@pytest.mark.parametrize(
    "code,status",
    [("llm_key_invalid", 400), ("llm_rate_limited", 429), ("llm_upstream", 502)],
)
def test_ask_llm_error_maps_to_status(monkeypatch, code, status):
    from app.agents import qa

    async def fake_embed(q):
        return [0.0]

    hit = SimpleNamespace(chapter_idx=0, char_start=0, char_end=2, text="你好", score=1.0)
    monkeypatch.setattr(qa, "embed_query", fake_embed)
    monkeypatch.setattr(qa, "search_chunks", lambda **k: [hit])
    monkeypatch.setattr("app.api.reader.get_session", _fake_session)
    monkeypatch.setattr(
        "app.api.reader.get_novel", lambda s, nid: SimpleNamespace(title="T")
    )
    monkeypatch.setattr("app.api.reader.get_progress", lambda s, u, n: 3)
    monkeypatch.setattr("app.api.reader.resolve_llm", lambda h, u: _RaiseLLM(code))
    user = SimpleNamespace(id=7, email="u@x", is_admin=False)
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_user_optional] = lambda: user
    try:
        with TestClient(app) as c:
            r = c.post("/ask", json={"novel_id": 1, "question": "q"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == status
    assert r.json()["detail"]["code"] == code
