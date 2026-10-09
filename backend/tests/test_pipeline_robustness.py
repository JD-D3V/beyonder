"""Pipeline robustness follow-ups: critic outage, batch races, unsafe URLs,
limiter cap, log redaction."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import current_user
from app.llm.client import LLMError
from app.main import app
from tests.test_llm_errors import _stub_graph_db


class _CriticDownLLM:
    """Succeeds on everything except the critic call."""

    model_name = "fake"

    def __init__(self, code):
        self.code = code

    async def generate(self, *a, **k):
        return "He was happy."

    async def generate_json(self, prompt, *, schema, **k):
        props = schema.get("properties", {})
        if "translation" in props:
            return {"translation": "Wang Lin came. He was happy.", "new_terms": []}
        if "terms" in props:
            return {"terms": []}
        if "flags" in props:
            raise LLMError(self.code, "critic down")
        return {"relations": []}


@pytest.mark.parametrize("code", ["llm_rate_limited", "llm_upstream"])
async def test_critic_outage_keeps_paid_translation(monkeypatch, code):
    from app.graph.orchestrator import run_translation_graph

    writes: list[str] = []
    _stub_graph_db(monkeypatch, writes)
    st = await run_translation_graph(
        llm=_CriticDownLLM(code), novel_id=1, novel_title="T",
        source_lang="zh", target_lang="en", chapter_idx=0,
    )
    assert st.translation.startswith("Wang Lin came")
    assert st.flags == []
    assert "upsert_translation" in writes


async def test_critic_outage_keeps_deterministic_flags():
    from app.graph.orchestrator import TranslateState, node_critic

    st = TranslateState(
        novel_id=1, novel_title="n", source_lang="zh", target_lang="en",
        chapter_idx=0, chapter_text="王林来了", translation="Someone 青云 came.",
        glossary=[("王林", "Wang Lin")],
    )
    out = await node_critic(st, {"configurable": {"llm": _CriticDownLLM("llm_upstream")}})
    assert out["done"] is True
    assert sorted(f["kind"] for f in out["flags"]) == ["glossary_drift", "untranslated"]


async def test_critic_invalid_key_still_aborts(monkeypatch):
    from app.graph.orchestrator import run_translation_graph

    writes: list[str] = []
    _stub_graph_db(monkeypatch, writes)
    with pytest.raises(LLMError) as ei:
        await run_translation_graph(
            llm=_CriticDownLLM("llm_key_invalid"), novel_id=1, novel_title="T",
            source_lang="zh", target_lang="en", chapter_idx=0,
        )
    assert ei.value.code == "llm_key_invalid"
    assert "upsert_translation" not in writes


# --- batch lost race -----------------------------------------------------


def test_batch_excludes_lost_race_chapters(monkeypatch):
    from contextlib import contextmanager

    from app.graph.orchestrator import TranslateState

    @contextmanager
    def sess():
        yield object()

    monkeypatch.setattr("app.api.translate.get_session", sess)
    monkeypatch.setattr(
        "app.api.translate.get_novel",
        lambda s, nid: SimpleNamespace(title="T", source_lang="zh"),
    )
    monkeypatch.setattr(
        "app.api.translate.chapter_rows",
        lambda s, nid, target_lang=None: [
            SimpleNamespace(idx=i, translated=False) for i in range(3)
        ],
    )

    async def graph(**kw):
        st = TranslateState(
            novel_id=1, novel_title="T", source_lang="zh", target_lang="en",
            chapter_idx=kw["chapter_idx"],
        )
        st.translation = "x"
        st.lost_race = kw["chapter_idx"] == 1
        return st

    monkeypatch.setattr("app.api.translate.run_translation_graph", graph)
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=1, email="u@x", is_admin=False
    )
    try:
        with TestClient(app) as c:
            r = c.post(
                "/translate/batch", json={"novel_id": 1, "limit": 3},
                headers={"X-LLM-Provider": "gemini", "X-LLM-Key": "k"},
            )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["translated"] == [0, 2]
    assert j["lost_race"] == [1]
    assert j["remaining"] == 0 and j["done"] is True


# --- unsafe URL ----------------------------------------------------------


def test_ingest_url_unsafe_is_400_with_code():
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=1, email="u@x", is_admin=False
    )
    try:
        with TestClient(app) as c:
            r = c.post(
                "/novels/ingest/url",
                json={"title": "t", "urls": ["http://127.0.0.1/secret"]},
            )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["code"] == "unsafe_url"
    assert d["detail"] == (
        "This URL can't be imported (only public http/https addresses are allowed)."
    )


async def test_scrape_many_propagates_unsafe_but_swallows_other(monkeypatch):
    from app.ingest import scraper

    async def fake(u):
        if "bad" in u:
            raise scraper.UnsafeURL("nope")
        raise RuntimeError("boom")

    monkeypatch.setattr(scraper, "scrape_url", fake)
    pages = await scraper.scrape_many(["http://ok.example/"])
    assert pages[0].text == ""
    with pytest.raises(scraper.UnsafeURL):
        await scraper.scrape_many(["http://bad.example/"])


# --- limiter cap ---------------------------------------------------------


def test_keyed_limiter_lru_capped():
    from app.common import rate_limit as rl

    rl._keyed.clear()
    first = rl.limiter_for("k0")
    for i in range(1, 1000):
        rl.limiter_for(f"k{i}")
    assert len(rl._keyed) == 1000
    rl.limiter_for("k0")  # touch: k1 is now the oldest
    rl.limiter_for("new")
    assert len(rl._keyed) == 1000
    assert "k0" in rl._keyed and "k1" not in rl._keyed
    assert rl.limiter_for("k0") is first
    rl._keyed.clear()


# --- log redaction -------------------------------------------------------


def test_redaction_recurses_into_nested():
    from app.common.logging import redact_llm_keys

    ev = {
        "event": "x",
        "headers": {"X-LLM-Key": "s1", "ok": 1, "deep": [{"Authorization": "s2"}]},
        "items": [{"password": "p", "keep": "v"}, ({"Token": "t"},)],
        "API_KEY": "k",
    }
    out = redact_llm_keys(None, "info", ev)
    assert out["headers"]["X-LLM-Key"] == "***"
    assert out["headers"]["ok"] == 1
    assert out["headers"]["deep"][0]["Authorization"] == "***"
    assert out["items"][0] == {"password": "***", "keep": "v"}
    assert out["items"][1][0]["Token"] == "***"
    assert out["API_KEY"] == "***"


@pytest.mark.db
def test_ingest_url_source_url_only_for_one_chapter_per_page(db_session, monkeypatch):
    from sqlalchemy import select

    from app.ingest.scraper import ScrapedPage
    from app.storage.models import Chapter

    def run(texts):
        async def fake(urls, concurrency=3):
            return [ScrapedPage(url=u, title=None, text=t) for u, t in zip(urls, texts)]

        monkeypatch.setattr("app.api.novels.scrape_many", fake)
        app.dependency_overrides[current_user] = lambda: SimpleNamespace(
            id=1, email="u@x", is_admin=False
        )
        try:
            with TestClient(app) as c:
                r = c.post(
                    "/novels/ingest/url",
                    json={"title": "t", "urls": [f"https://e.example/a/{i}" for i in range(len(texts))]},
                )
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200, r.text
        db_session.expire_all()
        return db_session.scalars(
            select(Chapter.source_url).where(Chapter.novel_id == r.json()["novel_id"]).order_by(Chapter.idx)
        ).all()

    # One chapter per page: every URL recorded.
    assert run(["Chapter 1\nfirst body text here.", "Chapter 2\nsecond body text here.", "plain prose page."]) == [
        "https://e.example/a/0", "https://e.example/a/1", "https://e.example/a/2",
    ]
    # One page holding three headed chapters: no URL recorded.
    assert run(["Chapter 1\naaa body.\n\nChapter 2\nbbb body.\n\nChapter 3\nccc body."]) == [None, None, None]
