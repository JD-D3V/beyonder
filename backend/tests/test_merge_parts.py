import pytest

from app.scripts.merge_parts import find_runs, merge_novel
from app.storage.models import (
    Chapter, Novel, ReadingProgress, ReviewFlag, Term, Translation, User,
)


def test_find_runs_only_exact_part_titles():
    titles = ["A", "A (2)", "A (3)", "B", "B (3)", "C (2)", None, "D", "D (2)"]
    assert find_runs(titles) == [[0, 1, 2], [7, 8]]


def test_find_runs_ignores_singletons_and_untitled():
    assert find_runs([None, None, "X", "Y"]) == []


def _book(s, titles, texts=None):
    n = Novel(title="Book", source_lang="zh")
    s.add(n)
    s.flush()
    chaps = []
    for i, t in enumerate(titles):
        text = (texts or {}).get(i, f"text{i}")
        c = Chapter(novel_id=n.id, idx=i, title=t, source_text=text, char_count=len(text))
        s.add(c)
        chaps.append(c)
    s.flush()
    return n, chaps


def _tr(s, chap, text, lang="en", pieces_done=None, title=None):
    s.add(Translation(
        chapter_id=chap.id, target_lang=lang, text=text, model="m",
        critic_passes=0, pieces_done=pieces_done, title=title,
    ))
    s.flush()


@pytest.mark.db
def test_merge_joins_text_reindexes_and_remaps(db_session):
    s = db_session
    n, ch = _book(s, ["A", "A (2)", "A (3)", "B", "C"])
    u = User(email="u@x", password_hash="x")
    s.add(u)
    s.flush()
    s.add_all([
        ReadingProgress(user_id=u.id, novel_id=n.id, chapter_idx=2),
        ReviewFlag(novel_id=n.id, chapter_idx=4, kind="idiom"),
        ReviewFlag(novel_id=n.id, chapter_idx=1, kind="idiom"),
        Term(novel_id=n.id, source_term="x", target_term="X", first_chapter=3),
        Term(novel_id=n.id, source_term="y", target_term="Y", first_chapter=4),
    ])
    for c in ch[:3]:
        _tr(s, c, f"en{c.idx}", title="Chapter A" if c.idx == 0 else None)
    _tr(s, ch[3], "enB")

    plan = merge_novel(s, n.id)
    s.flush()
    s.expire_all()

    assert plan.runs == [[0, 1, 2]]
    rows = s.query(Chapter).filter_by(novel_id=n.id).order_by(Chapter.idx).all()
    assert [(c.idx, c.title) for c in rows] == [(0, "A"), (1, "B"), (2, "C")]
    assert rows[0].source_text == "text0\n\ntext1\n\ntext2"
    assert rows[0].char_count == len(rows[0].source_text)
    t0 = s.query(Translation).filter_by(chapter_id=rows[0].id).one()
    assert t0.text == "en0\n\nen1\n\nen2" and t0.title == "Chapter A"
    assert s.query(Translation).filter_by(chapter_id=rows[1].id).one().text == "enB"
    assert s.query(ReadingProgress).one().chapter_idx == 0
    assert sorted(f.chapter_idx for f in s.query(ReviewFlag)) == [0, 2]
    assert {t.source_term: t.first_chapter for t in s.query(Term)} == {"x": 1, "y": 2}


@pytest.mark.db
def test_incomplete_part_translation_drops_the_language(db_session):
    s = db_session
    n, ch = _book(s, ["A", "A (2)", "Z"])
    _tr(s, ch[0], "en0")
    _tr(s, ch[1], "partial", pieces_done=1)  # not complete
    _tr(s, ch[0], "fr0", lang="fr")
    _tr(s, ch[1], "fr1", lang="fr")
    merge_novel(s, n.id)
    s.flush()
    s.expire_all()
    head = s.query(Chapter).filter_by(novel_id=n.id, idx=0).one()
    langs = {t.target_lang: t.text for t in s.query(Translation).filter_by(chapter_id=head.id)}
    assert langs == {"fr": "fr0\n\nfr1"}


@pytest.mark.db
def test_dry_run_changes_nothing(db_session):
    s = db_session
    n, _ = _book(s, ["A", "A (2)"])
    plan = merge_novel(s, n.id, dry_run=True)
    s.flush()
    assert plan.runs == [[0, 1]] and plan.chapters_after == 1
    assert s.query(Chapter).filter_by(novel_id=n.id).count() == 2


@pytest.mark.db
def test_multiple_runs_stay_contiguous(db_session):
    s = db_session
    n, _ = _book(s, ["A", "A (2)", "M", "B", "B (2)", "B (3)", "N"])
    plan = merge_novel(s, n.id)
    s.flush()
    s.expire_all()
    rows = s.query(Chapter).filter_by(novel_id=n.id).order_by(Chapter.idx).all()
    assert [(c.idx, c.title) for c in rows] == [(0, "A"), (1, "M"), (2, "B"), (3, "N")]
    assert plan.mapping == {0: 0, 1: 0, 2: 1, 3: 2, 4: 2, 5: 2, 6: 3}


@pytest.mark.db
def test_dropped_translation_counted_and_flags_deleted(db_session):
    s = db_session
    n, ch = _book(s, ["A", "A (2)", "B", "C", "C (2)"])
    _tr(s, ch[0], "en0")
    _tr(s, ch[1], "partial", pieces_done=1)  # A: en dropped
    _tr(s, ch[3], "enC")
    _tr(s, ch[4], "enC2")  # C: complete, kept
    s.add_all([
        ReviewFlag(novel_id=n.id, chapter_idx=0, kind="idiom"),
        ReviewFlag(novel_id=n.id, chapter_idx=1, kind="idiom"),
        ReviewFlag(novel_id=n.id, chapter_idx=3, kind="idiom"),
    ])
    s.flush()
    assert merge_novel(s, n.id, dry_run=True).dropped_translations == 1
    plan = merge_novel(s, n.id)
    s.flush()
    assert plan.dropped_translations == 1
    # Only the kept run's flag survives, remapped (old 3 -> new 2).
    assert [f.chapter_idx for f in s.query(ReviewFlag)] == [2]


@pytest.mark.asyncio
async def test_rebuild_failure_is_reported_and_others_continue(monkeypatch, capsys):
    from app.scripts import merge_parts as mp
    from contextlib import contextmanager
    from types import SimpleNamespace

    @contextmanager
    def sess():
        yield SimpleNamespace(scalars=lambda q: [1, 2])

    calls = []

    async def rebuild(nid):
        calls.append(nid)
        if nid == 1:
            raise RuntimeError("qdrant down")
        return 5

    monkeypatch.setattr(mp, "get_session", sess)
    monkeypatch.setattr(mp, "_rebuild_vectors", rebuild)
    failed = await mp._run(None, False, reembed_only=True)
    out = capsys.readouterr().out
    assert failed == 1 and calls == [1, 2]
    assert 'Vectors for novel 1 could not be rebuilt: qdrant down. Run `make reembed ARGS="--novel 1"`' in out
    assert "re-embedded 5 chunks" in out


@pytest.mark.asyncio
async def test_merge_then_rebuild_failure_exits_nonzero(monkeypatch, capsys):
    from app.scripts import merge_parts as mp
    from contextlib import contextmanager
    from types import SimpleNamespace

    @contextmanager
    def sess():
        yield SimpleNamespace(scalars=lambda q: [7])

    async def rebuild(nid):
        raise RuntimeError("boom")

    monkeypatch.setattr(mp, "get_session", sess)
    monkeypatch.setattr(
        mp, "merge_novel",
        lambda s, nid, dry_run=False: mp.MergePlan(
            nid, [[0, 1]], {0: 0, 1: 0}, 2, 1, dropped_translations=3
        ),
    )
    monkeypatch.setattr(mp, "_rebuild_vectors", rebuild)
    assert await mp._run(None, False) == 1
    out = capsys.readouterr().out
    assert "3 existing translation(s) were dropped" in out
    assert "could not be rebuilt" in out
