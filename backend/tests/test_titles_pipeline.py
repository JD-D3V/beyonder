"""Titles through the pipeline (single-pass graph, resumable step) and the routes."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import current_user, current_user_optional, require_admin
from app.graph import orchestrator as orch
from app.graph import resumable as r
from app.main import app
from tests.test_gaps_resumable import _setup


class _Llm:
    model_name = "fake"


# --- single-pass graph -----------------------------------------------------


def _state(idx=0, title="第一章 青云山下", need_novel=True):
    return orch.TranslateState(
        novel_id=1, novel_title="修仙传", source_lang="zh", target_lang="en",
        chapter_idx=idx, chapter_text="正文", chapter_title=title,
        need_novel_title=need_novel, glossary=[("青云山", "Azure Cloud Mountain")],
    )


@pytest.mark.asyncio
async def test_node_translate_translates_chapter_and_novel_title(monkeypatch):
    seen = []

    async def tc(text, **k):
        return SimpleNamespace(translation="Body", new_terms=[])

    async def tt(client, title, glossary, *a, **k):
        seen.append((title, list(glossary)))
        return "EN:" + title

    monkeypatch.setattr(orch, "translate_chapter", tc)
    monkeypatch.setattr(orch, "translate_title", tt)
    out = await orch.node_translate(_state(), {"configurable": {"llm": _Llm()}})
    assert out["title_en"] == "EN:第一章 青云山下"
    assert out["novel_title_en"] == "EN:修仙传"
    assert seen[0][1] == [("青云山", "Azure Cloud Mountain")]


@pytest.mark.asyncio
async def test_node_translate_skips_novel_title_off_chapter_zero(monkeypatch):
    async def tc(text, **k):
        return SimpleNamespace(translation="Body", new_terms=[])

    async def tt(client, title, glossary, *a, **k):
        return "EN"

    monkeypatch.setattr(orch, "translate_chapter", tc)
    monkeypatch.setattr(orch, "translate_title", tt)
    out = await orch.node_translate(
        _state(idx=3, need_novel=False), {"configurable": {"llm": _Llm()}}
    )
    assert out["title_en"] == "EN"
    assert out["novel_title_en"] is None


@pytest.mark.asyncio
async def test_node_persist_stores_title_and_novel_title(monkeypatch):
    saved = {}
    novel = SimpleNamespace(title_en=None)

    @contextmanager
    def sess():
        yield object()

    def upsert(s, **k):
        saved.update(k)
        return True

    monkeypatch.setattr(orch, "get_session", sess)
    monkeypatch.setattr(orch, "upsert_translation", upsert)
    monkeypatch.setattr(orch, "replace_open_flags", lambda *a, **k: None)
    monkeypatch.setattr(orch, "get_novel", lambda s, n: novel)
    monkeypatch.setattr(
        orch, "update_novel",
        lambda s, nid, **f: saved.__setitem__("novel", f),
    )
    st = _state()
    st.translation = "Body"
    st.chapter_db_id = 9
    st.title_en = "Chapter 1: Below Azure Cloud Mountain"
    st.novel_title_en = "Tale of Cultivation"
    await orch.node_persist(st, {"configurable": {"llm": _Llm()}})
    assert saved["title"] == "Chapter 1: Below Azure Cloud Mountain"
    assert saved["novel"] == {"title_en": "Tale of Cultivation"}


# --- resumable -------------------------------------------------------------


@pytest.mark.asyncio
async def test_translate_step_titles_on_first_call(monkeypatch):
    _setup(monkeypatch)
    chap = SimpleNamespace(id=5, source_text="one piece only", title="第一章")
    monkeypatch.setattr(r, "get_chapter_by_idx", lambda s, n, i: chap)
    monkeypatch.setattr(
        r, "get_novel", lambda s, n: SimpleNamespace(title="修仙传", title_en=None)
    )
    calls, novel_updates, titles = [], [], []

    async def tt(client, title, glossary, *a, **k):
        calls.append(title)
        return "EN:" + title

    def upsert(s, *, text, **k):
        titles.append(k.get("title"))
        return True

    monkeypatch.setattr(r, "translate_title", tt)
    monkeypatch.setattr(r, "upsert_translation", upsert)
    monkeypatch.setattr(r, "update_novel", lambda s, nid, **f: novel_updates.append(f))
    res = await r.translate_step(llm=_Llm(), novel_id=1, chapter_idx=0)
    assert res.title_en == "EN:第一章"
    assert calls == ["第一章", "修仙传"]
    assert titles == ["EN:第一章"]
    assert novel_updates == [{"title_en": "EN:修仙传"}]


@pytest.mark.asyncio
async def test_translate_step_does_not_retitle_when_resuming(monkeypatch):
    _setup(monkeypatch)
    chap = SimpleNamespace(id=5, source_text="a\n\nb", title="第一章")
    monkeypatch.setattr(r, "get_chapter_by_idx", lambda s, n, i: chap)
    monkeypatch.setattr(r, "split_paragraphs", lambda t: ["a", "b"])
    monkeypatch.setattr(
        r, "get_translation",
        lambda s, **k: SimpleNamespace(text="A", pieces_done=1),
    )
    calls = []

    async def tt(*a, **k):
        calls.append(1)
        return "x"

    monkeypatch.setattr(r, "translate_title", tt)
    res = await r.translate_step(llm=_Llm(), novel_id=1, chapter_idx=0)
    assert res.title_en is None
    assert calls == []


# --- routes ----------------------------------------------------------------


@contextmanager
def _fake_session():
    yield object()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _as_admin():
    admin = SimpleNamespace(id=1, email="a@x", is_admin=True)
    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[current_user_optional] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin


def test_chapter_list_and_detail_carry_title_en(client, monkeypatch):
    import app.api.novels as novels
    from app.storage.repository import ChapterRow

    monkeypatch.setattr(novels, "get_session", _fake_session)
    monkeypatch.setattr(novels, "get_novel", lambda s, n: object())
    monkeypatch.setattr(
        novels, "chapter_rows",
        lambda s, n, target_lang: [
            ChapterRow(idx=0, title="第一章", char_count=3, translated=True,
                       title_en="Chapter 1"),
            ChapterRow(idx=1, title="第二章", char_count=3, translated=False),
        ],
    )
    rows = client.get("/novels/1/chapters").json()
    assert [r_["title_en"] for r_ in rows] == ["Chapter 1", None]

    chap = SimpleNamespace(idx=0, title="第一章", char_count=3, source_text="x", id=4)
    monkeypatch.setattr(novels, "get_chapter_by_idx", lambda s, n, i: chap)
    monkeypatch.setattr(
        novels, "get_translation",
        lambda s, **k: SimpleNamespace(
            text="t", model="m", critic_passes=0, pieces_done=None,
            title="Chapter 1",
        ),
    )
    assert client.get("/novels/1/chapters/0").json()["title_en"] == "Chapter 1"


def test_patch_accepts_title_en(client, monkeypatch):
    import app.api.novels as novels

    _as_admin()
    seen = {}
    monkeypatch.setattr(novels, "get_session", _fake_session)
    monkeypatch.setattr(
        novels, "update_novel", lambda s, nid, **f: seen.update(f) or object()
    )

    async def fake_get(novel_id):
        return {"id": 1, "title": "t", "source_lang": "zh"}

    monkeypatch.setattr(novels, "get_novel_route", fake_get)
    res = client.patch("/novels/1", json={"title_en": "Tale"})
    assert res.status_code == 200
    assert seen["title_en"] == "Tale"


def test_novel_out_has_title_en():
    import app.api.novels as novels

    n = SimpleNamespace(
        id=1, title="修仙传", title_en="Tale", author=None, description=None,
        tags=None, status="ongoing", source_lang="zh", source_url=None,
        updated_at=None,
    )
    assert novels._novel_out(n, 1, 1, 0).title_en == "Tale"


def test_titles_translate_route(client, monkeypatch):
    import app.api.novels as novels

    _as_admin()
    rows = {10: SimpleNamespace(title=None), 11: SimpleNamespace(title=None)}
    novel = SimpleNamespace(title="修仙传", title_en=None)
    updates = []

    class Sess:
        def get(self, model, pk):
            return rows.get(pk)

    @contextmanager
    def sess():
        yield Sess()

    monkeypatch.setattr(novels, "get_session", sess)
    monkeypatch.setattr(novels, "get_novel", lambda s, n: novel)
    monkeypatch.setattr(novels, "get_terms_for_chapters", lambda *a, **k: [])
    monkeypatch.setattr(novels, "resolve_llm", lambda h, u: _Llm())
    monkeypatch.setattr(
        novels, "untitled_translations",
        lambda s, n: [
            (SimpleNamespace(id=10), "第一章"), (SimpleNamespace(id=11), "第二章"),
        ],
    )
    batches = []

    async def batch(llm, titles, glossary, *a, **k):
        batches.append(list(titles))
        return ["Chapter 1", "Chapter 2"]

    async def one(llm, title, glossary, *a, **k):
        return "Tale"

    monkeypatch.setattr(novels, "translate_titles_batch", batch)
    monkeypatch.setattr(novels, "translate_title", one)
    monkeypatch.setattr(novels, "update_novel", lambda s, nid, **f: updates.append(f))
    res = client.post("/novels/1/titles/translate")
    assert res.status_code == 200
    assert res.json() == {"chapters": 2, "novel": True}
    assert batches == [["第一章", "第二章"]]
    assert rows[10].title == "Chapter 1" and rows[11].title == "Chapter 2"
    assert updates == [{"title_en": "Tale"}]


def test_titles_translate_route_requires_admin(client):
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=2, email="u@x", is_admin=False
    )
    assert client.post("/novels/1/titles/translate").status_code in (401, 403)


# --- title failures never discard the chapter / first-call stalls ------------


@pytest.mark.asyncio
async def test_node_translate_survives_title_llm_error(monkeypatch):
    from app.llm.client import LLMError

    async def tc(text, **k):
        return SimpleNamespace(translation="Body", new_terms=[])

    async def tt(client, title, glossary, *a, **k):
        raise LLMError("llm_upstream", "boom")

    monkeypatch.setattr(orch, "translate_chapter", tc)
    monkeypatch.setattr(orch, "translate_title", tt)
    out = await orch.node_translate(_state(), {"configurable": {"llm": _Llm()}})
    assert out["translation"] == "Body"
    assert out["title_en"] is None and out["novel_title_en"] is None


@pytest.mark.asyncio
async def test_node_translate_novel_title_error_keeps_chapter_title(monkeypatch):
    from app.llm.client import LLMError

    async def tc(text, **k):
        return SimpleNamespace(translation="Body", new_terms=[])

    async def tt(client, title, glossary, *a, **k):
        if title == "修仙传":
            raise LLMError("llm_upstream", "boom")
        return "EN"

    monkeypatch.setattr(orch, "translate_chapter", tc)
    monkeypatch.setattr(orch, "translate_title", tt)
    out = await orch.node_translate(_state(), {"configurable": {"llm": _Llm()}})
    assert out["title_en"] == "EN" and out["novel_title_en"] is None


def test_clean_title_truncates_to_512():
    from app.agents.translator import _clean_title

    assert len(_clean_title("x" * 2000)) == 512


@pytest.mark.asyncio
async def test_translate_step_stall_before_first_piece_spends_no_title_call(monkeypatch):
    _setup(monkeypatch)
    chap = SimpleNamespace(id=5, source_text="one piece only", title="第一章")
    monkeypatch.setattr(r, "get_chapter_by_idx", lambda s, n, i: chap)
    monkeypatch.setattr(
        r, "get_novel", lambda s, n: SimpleNamespace(title="修仙传", title_en=None)
    )
    calls = []

    async def tt(*a, **k):
        calls.append(1)
        return "x"

    async def blank(piece, **k):
        return SimpleNamespace(translation="", new_terms=[])

    monkeypatch.setattr(r, "translate_title", tt)
    monkeypatch.setattr(r, "translate_paragraph", blank)
    res = await r.translate_step(llm=_Llm(), novel_id=1, chapter_idx=0)
    assert res.stalled and calls == []


@pytest.mark.asyncio
async def test_translate_step_title_llm_error_keeps_the_piece(monkeypatch):
    from app.llm.client import LLMError

    _setup(monkeypatch)
    chap = SimpleNamespace(id=5, source_text="one piece only", title="第一章")
    monkeypatch.setattr(r, "get_chapter_by_idx", lambda s, n, i: chap)
    saved = []

    async def tt(*a, **k):
        raise LLMError("llm_upstream", "boom")

    def upsert(s, *, text, **k):
        saved.append((text, k.get("title")))
        return True

    monkeypatch.setattr(r, "translate_title", tt)
    monkeypatch.setattr(r, "upsert_translation", upsert)
    res = await r.translate_step(llm=_Llm(), novel_id=1, chapter_idx=0)
    assert saved == [("draft", None)] and res.title_en is None
