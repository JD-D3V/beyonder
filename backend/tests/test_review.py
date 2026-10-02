import pytest
from fastapi.testclient import TestClient

from app.agents.critic import critique_translation
from app.auth.deps import require_admin
from app.graph.orchestrator import build_translation_graph
from app.main import app
from app.review import checks


def test_untranslated_detects_cjk_runs():
    assert checks.untranslated_spans("He said 王林 and 青云门 left.") == ["王林", "青云门"]


def test_single_cjk_punctuation_not_flagged():
    assert checks.untranslated_spans("He said 。 and 王 left，ok") == []


def test_drift_fix_replaces_variant():
    fixed, flags = checks.fix_glossary_drift(
        "王林来了", "Wang Lyn arrived.", [("王林", "Wang Lin")], {"王林": ["Wang Lyn"]}
    )
    assert fixed == "Wang Lin arrived."
    assert flags == []


def test_drift_unfixable_is_flagged():
    fixed, flags = checks.fix_glossary_drift(
        "王林来了", "Someone arrived.", [("王林", "Wang Lin")], {}
    )
    assert fixed == "Someone arrived."
    assert len(flags) == 1
    assert flags[0]["kind"] == "glossary_drift"
    assert flags[0]["source_span"] == "王林"
    assert flags[0]["target_span"] == ""


def test_graph_has_no_retry_edge():
    g = build_translation_graph().get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert ("critic", "translate") not in edges
    assert ("translate", "critic") in edges
    assert ("critic", "relate") in edges
    assert ("relate", "persist") in edges


class _BoomLLM:
    model_name = "boom"

    async def generate_json(self, *a, **k):
        raise RuntimeError("down")


class _FlagLLM:
    model_name = "f"

    async def generate_json(self, *a, **k):
        return {"flags": [
            {"kind": "pronoun", "source_span": "他", "target_span": "he", "note": "?"},
            {"kind": "bogus", "source_span": "x", "target_span": "y", "note": ""},
        ]}


@pytest.mark.asyncio
async def test_critic_llm_failure_still_saves_translation():
    res = await critique_translation(
        client=_BoomLLM(), source="王林来了", candidate="Someone 青云 came.",
        glossary=[("王林", "Wang Lin")],
    )
    kinds = sorted(f["kind"] for f in res.flags)
    assert kinds == ["glossary_drift", "untranslated"]
    assert res.fixed_text == "Someone 青云 came."


@pytest.mark.asyncio
async def test_critic_llm_flags_validated():
    res = await critique_translation(
        client=_FlagLLM(), source="他来了", candidate="He came.", glossary=[]
    )
    assert [f["kind"] for f in res.flags] == ["pronoun"]


@pytest.mark.asyncio
async def test_node_critic_keeps_translation_on_llm_failure():
    from app.graph.orchestrator import TranslateState, node_critic

    st = TranslateState(
        novel_id=1, novel_title="n", source_lang="zh", target_lang="en",
        chapter_idx=0, chapter_text="王林来了", translation="Wang Lyn came.",
        glossary=[("王林", "Wang Lin")], variants={"王林": ["Wang Lyn"]},
    )
    out = await node_critic(st, {"configurable": {"llm": _BoomLLM()}})
    assert out["translation"] == "Wang Lin came."
    assert out["flags"] == []
    assert out["done"] is True


class _Admin:
    id = 1
    is_admin = True


def test_resolve_route_requires_admin():
    with TestClient(app) as c:
        r = c.post("/flags/1/resolve")
    assert r.status_code in (401, 403)


def test_flags_route_public_and_resolve(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    import app.api.reader as reader

    row = SimpleNamespace(
        id=3, novel_id=1, chapter_idx=2, kind="idiom", source_span="a",
        target_span="b", note="n", status="open", created_at=None, resolved_by=None,
    )

    @contextmanager
    def fake_session():
        yield object()

    seen = {}

    def fake_list(s, novel_id, status, chapter):
        seen["args"] = (novel_id, status, chapter)
        return [row]

    def fake_resolve(s, flag_id, user_id):
        row.status, row.resolved_by = "resolved", user_id
        return row

    monkeypatch.setattr(reader, "get_session", fake_session)
    monkeypatch.setattr(reader, "list_flags", fake_list)
    monkeypatch.setattr(reader, "resolve_flag", fake_resolve)
    app.dependency_overrides[require_admin] = lambda: _Admin()
    try:
        with TestClient(app) as c:
            r = c.get("/novels/1/flags?status=open&chapter=2")
            assert r.status_code == 200
            assert r.json()[0]["kind"] == "idiom"
            assert seen["args"] == (1, "open", 2)
            r = c.post("/flags/3/resolve")
            assert r.status_code == 200
            assert r.json()["status"] == "resolved"
    finally:
        app.dependency_overrides.clear()


pytestmark_db = pytest.mark.db


@pytest.mark.db
def test_replace_open_flags_keeps_resolved(db_session):
    from app.storage.models import Novel, User
    from app.storage.repository import (
        list_flags, load_variants, replace_open_flags, resolve_flag,
    )

    u = User(email="a@example.com", password_hash="x")
    n = Novel(title="n", source_lang="zh")
    db_session.add_all([u, n])
    db_session.flush()
    f1 = {"kind": "glossary_drift", "source_span": "王林", "target_span": "", "note": ""}
    replace_open_flags(db_session, n.id, 1, [f1, dict(f1, kind="idiom")])
    rows = list_flags(db_session, n.id, "open", 1)
    assert len(rows) == 2
    resolve_flag(db_session, rows[0].id, u.id)
    replace_open_flags(db_session, n.id, 1, [f1])
    assert len(list_flags(db_session, n.id, "open", 1)) == 1
    assert len(list_flags(db_session, n.id, "resolved", 1)) == 1
    assert load_variants(db_session, n.id) == {}
