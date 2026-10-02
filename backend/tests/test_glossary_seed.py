import pytest

from app.glossary.seed import SeedTerm, load_seed, match_seed


def test_seed_yaml_loads_and_has_no_duplicate_sources():
    seed = load_seed()
    assert len(seed) >= 150
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
