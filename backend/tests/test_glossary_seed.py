import pytest

from app.glossary.seed import SeedTerm, load_seed, match_seed


def test_seed_yaml_loads_and_has_no_duplicate_sources():
    seed = load_seed()
    assert len(seed) >= 100
    assert all(isinstance(t, SeedTerm) for t in seed)
    sources = [t.source for t in seed]
    assert len(sources) == len(set(sources))
    kinds = {"character", "sect", "technique", "realm", "item", "other"}
    assert all(t.kind in kinds and t.source and t.target for t in seed)


def test_match_prefers_longest():
    hits = match_seed("他已是金丹期修士", set())
    srcs = {h["source_term"] for h in hits}
    assert "金丹期" in srcs
    assert "金丹" not in srcs
    h = next(h for h in hits if h["source_term"] == "金丹期")
    assert h["confidence"] == 0.9 and h["notes"] == "seed"
    assert h["target_term"] and h["kind"] == "realm"


def test_match_skips_known():
    hits = match_seed("师兄与长老", {"师兄"})
    srcs = {h["source_term"] for h in hits}
    assert "师兄" not in srcs and "长老" in srcs


def test_match_no_duplicates_and_empty():
    assert match_seed("", set()) == []
    hits = match_seed("长老长老长老", set())
    assert [h["source_term"] for h in hits].count("长老") == 1


@pytest.mark.db
def test_upsert_does_not_overwrite_locked(db_session):
    from app.storage.models import Novel, Term
    from app.storage.repository import upsert_terms

    n = Novel(title="n", source_lang="zh")
    db_session.add(n)
    db_session.flush()
    db_session.add(
        Term(novel_id=n.id, source_term="师兄", target_term="Elder Brother",
             target_lang="en", kind="other", confidence=0.1, locked=True)
    )
    db_session.flush()
    upsert_terms(
        db_session, novel_id=n.id,
        entries=[{"source_term": "师兄", "target_term": "Senior Brother",
                  "confidence": 0.99, "first_chapter": 0}],
    )
    t = db_session.query(Term).filter_by(novel_id=n.id, source_term="师兄").one()
    assert t.target_term == "Elder Brother" and t.locked is True


@pytest.mark.asyncio
async def test_seed_node_adds_terms_and_glossary():
    from app.graph.orchestrator import TranslateState, node_seed

    st = TranslateState(
        novel_id=1, novel_title="t", source_lang="zh", target_lang="en",
        chapter_idx=7, chapter_text="师兄是金丹期", glossary=[("师兄", "Big Bro")],
    )
    out = await node_seed(st, {"configurable": {"translated_by": 3}})
    srcs = [t["source_term"] for t in out["new_terms"]]
    assert srcs == ["金丹期"]
    assert out["new_terms"][0]["first_chapter"] == 7
    assert out["new_terms"][0]["added_by"] == 3
    assert ("师兄", "Big Bro") in out["glossary"]


def test_common_words_do_not_match():
    # 老夫/仙人/在下/大人 were pruned: plain words must not hit the seed.
    assert match_seed("老夫人在下面看仙人掌，大人们走了", set()) == []


def test_exclude_list_blocks_longer_words():
    assert match_seed("他是个公子哥", set()) == []
    assert match_seed("拜见老祖宗", set()) == []
    assert match_seed("《弟子规》", set()) == []
    srcs = {h["source_term"] for h in match_seed("公子哥与公子", set())}
    assert srcs == {"公子"}  # the bare 公子 still matches


def test_exclude_entries_are_loaded():
    by = {t.source: t for t in load_seed()}
    assert "公子哥" in by["公子"].exclude


def test_seed_consistency():
    by = {t.source: t for t in load_seed()}
    assert by["少主"].target == "Young Lord"
    assert by["修仙界"].kind == "other"
    assert "仙人" not in by


@pytest.mark.db
def test_insert_seed_terms_never_touches_existing(db_session):
    from app.storage.models import Novel, Term
    from app.storage.repository import insert_seed_terms

    n = Novel(title="n", source_lang="zh")
    db_session.add(n)
    db_session.flush()
    db_session.add(Term(novel_id=n.id, source_term="师兄", target_term="Mine",
                        target_lang="en", kind="other", confidence=0.1,
                        first_chapter=9))
    db_session.flush()
    made = insert_seed_terms(db_session, novel_id=n.id, entries=[
        {"source_term": "师兄", "target_term": "Senior Brother", "confidence": 0.9,
         "first_chapter": 0},
        {"source_term": "长老", "target_term": "Elder", "first_chapter": 2},
    ])
    assert [t.source_term for t in made] == ["长老"]
    t = db_session.query(Term).filter_by(novel_id=n.id, source_term="师兄").one()
    assert (t.target_term, t.first_chapter, t.confidence) == ("Mine", 9, 0.1)


def test_insert_seed_terms_skips_existing_no_db():
    from types import SimpleNamespace

    from app.storage.repository import insert_seed_terms

    added = []

    class S:
        def execute(self, stmt):
            # Pretend only 师兄 exists.
            hit = "师兄" in str(stmt.compile(compile_kwargs={"literal_binds": True}))
            return SimpleNamespace(first=lambda: (1,) if hit else None)

        def add(self, t):
            added.append(t.source_term)

        def flush(self):
            pass

    made = insert_seed_terms(S(), novel_id=1, entries=[
        {"source_term": "师兄", "target_term": "x"},
        {"source_term": "长老", "target_term": "Elder"},
        {"source_term": "长老", "target_term": "Elder"},
    ])
    assert added == ["长老"] and len(made) == 1
