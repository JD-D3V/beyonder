from contextlib import contextmanager
from types import SimpleNamespace

from app.graph import orchestrator as o


@contextmanager
def _sess():
    yield object()


def _term(i, src):
    return SimpleNamespace(
        id=i, locked=False, source_term=src, target_term=src + "-en",
        kind="other", first_chapter=0, confidence=0.5,
    )


def _stub(monkeypatch):
    monkeypatch.setattr(o, "get_session", _sess)
    monkeypatch.setattr(o, "insert_relations", lambda *a, **k: None)
    monkeypatch.setattr(o, "upsert_translation", lambda *a, **k: True)
    monkeypatch.setattr(o, "replace_open_flags", lambda *a, **k: None)


def _state(new_terms):
    return o.TranslateState(
        novel_id=1, novel_title="n", source_lang="zh", target_lang="en",
        chapter_idx=0, chapter_text="你好", chapter_db_id=5, translation="hello",
        new_terms=new_terms,
    )


CFG = {"configurable": {"llm": SimpleNamespace(model_name="m")}}


async def test_persist_reports_only_rows_created_this_call(monkeypatch):
    _stub(monkeypatch)
    # The seed term already existed: insert_seed_terms creates nothing.
    monkeypatch.setattr(o, "insert_seed_terms", lambda s, **k: [])

    def fake_upsert(s, *, entries, created_out=None, **k):
        # "new" is created; "old" pre-exists so it is not reported.
        for e in entries:
            if e["source_term"] == "new":
                created_out.append(_term(7, "new"))
        return []

    monkeypatch.setattr(o, "upsert_terms", fake_upsert)
    out = await o.node_persist(
        _state([
            {"source_term": "seeded", "target_term": "x", "_seed": True},
            {"source_term": "old", "target_term": "y"},
            {"source_term": "new", "target_term": "z"},
        ]),
        CFG,
    )
    assert [t["id"] for t in out["new_terms"]] == [7]
    assert [t["source_term"] for t in out["new_terms"]] == ["new"]


async def test_persist_reports_nothing_when_all_preexisting(monkeypatch):
    _stub(monkeypatch)
    monkeypatch.setattr(o, "insert_seed_terms", lambda s, **k: [])
    monkeypatch.setattr(o, "upsert_terms", lambda s, **k: [])
    out = await o.node_persist(
        _state([{"source_term": "old", "target_term": "y"}]), CFG
    )
    assert out["new_terms"] == []
