from contextlib import contextmanager
from types import SimpleNamespace

from app.graph import resumable as r


class _Row:
    def __init__(self, text, pieces_done=None):
        self.text = text
        self.pieces_done = pieces_done


class _Sess:
    """execute(...).scalar_one_or_none() returns the (mutable) stored row."""

    def __init__(self, holder):
        self.holder = holder

    def execute(self, *a, **k):
        row = self.holder["row"]
        return SimpleNamespace(scalar_one_or_none=lambda: row)


def _setup(monkeypatch, *, stored_override=None, fixed="FIXED"):
    holder = {"row": None}
    flags = []

    @contextmanager
    def sess():
        yield _Sess(holder)

    chap = SimpleNamespace(id=5, source_text="one piece only")
    monkeypatch.setattr(r, "get_session", sess)
    monkeypatch.setattr(r, "get_chapter_by_idx", lambda s, n, i: chap)
    monkeypatch.setattr(r, "get_novel", lambda s, n: SimpleNamespace(title="T"))
    monkeypatch.setattr(r, "get_translation", lambda s, **k: None)
    monkeypatch.setattr(r, "get_terms_for_chapters", lambda *a, **k: [])
    monkeypatch.setattr(r, "match_seed", lambda *a, **k: [])
    monkeypatch.setattr(r, "load_variants", lambda *a, **k: {})
    monkeypatch.setattr(r, "term_dicts", lambda t: [])

    async def tp(piece, **k):
        return SimpleNamespace(translation="draft", new_terms=[])

    async def rels(**k):
        return []

    def upsert(s, *, text, **k):
        holder["row"] = _Row(stored_override if stored_override is not None else text)
        return True

    monkeypatch.setattr(r, "translate_paragraph", tp)
    monkeypatch.setattr(r, "extract_relations_from_chapter", rels)
    monkeypatch.setattr(r, "upsert_translation", upsert)
    monkeypatch.setattr(
        r, "deterministic_flags",
        lambda src, cand, gl, var: (fixed, [{"kind": "untranslated"}]),
    )
    monkeypatch.setattr(r, "replace_open_flags", lambda s, n, i, f: flags.append(f))
    return holder, flags


LLM = SimpleNamespace(model_name="m")


async def test_completion_runs_qa_and_rewrites_when_text_unchanged(monkeypatch):
    holder, flags = _setup(monkeypatch)
    res = await r.translate_step(llm=LLM, novel_id=1, chapter_idx=0)
    assert res.complete
    assert holder["row"].text == "FIXED"
    assert flags == [[{"kind": "untranslated"}]]


async def test_completion_does_not_rewrite_when_text_changed_meanwhile(monkeypatch):
    holder, flags = _setup(monkeypatch, stored_override="edited by someone else")
    res = await r.translate_step(llm=LLM, novel_id=1, chapter_idx=0)
    assert res.complete
    assert holder["row"].text == "edited by someone else"
    assert flags == []


async def test_qa_failure_is_best_effort(monkeypatch):
    holder, flags = _setup(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("qa broke")

    monkeypatch.setattr(r, "deterministic_flags", boom)
    res = await r.translate_step(llm=LLM, novel_id=1, chapter_idx=0)
    assert res.complete and holder["row"].text == "draft"
