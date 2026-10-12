"""Private books: the visibility matrix on every route that takes a novel id,
plus catalog / rankings / view counting / import behaviour.

The matrix test is the one that matters: for a private book, every route that
names a novel (directly, or through a comment/review/flag that belongs to one)
must 404 for anonymous callers and other users, and work for the owner and an
admin. A route added without ``visible_novel_or_404`` fails here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import current_user, current_user_optional
from app.main import app

pytestmark = pytest.mark.db

KEY = {"X-LLM-Provider": "gemini", "X-LLM-Key": "k"}


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def world(db_session):
    """A private book owned by ``owner`` with a chapter, term, flag, review,
    comment and cover, plus the users who might poke at it."""
    from app.storage.models import (
        Chapter, Comment, ImportJob, Novel, Review, ReviewFlag, Term, User,
    )
    from app.storage.repository import set_cover

    s = db_session
    users = {}
    for name, admin in (("owner", False), ("other", False), ("admin", True)):
        u = User(email=f"{name}@x.com", password_hash="x", is_admin=admin)
        s.add(u)
        users[name] = u
    s.flush()
    novel = Novel(
        title="Secret", source_lang="zh", visibility="private",
        owner_id=users["owner"].id,
    )
    s.add(novel)
    s.flush()
    for i in range(2):
        s.add(Chapter(
            novel_id=novel.id, idx=i, title=f"c{i}", source_text="你好" * 10,
            char_count=20,
        ))
    term = Term(novel_id=novel.id, source_term="林", target_term="Lin",
                kind="person", first_chapter=0)
    flag = ReviewFlag(novel_id=novel.id, chapter_idx=0, kind="idiom",
                      source_span="a", target_span="b", note="n")
    review = Review(novel_id=novel.id, user_id=users["other"].id, rating=4, body="hm")
    comment = Comment(novel_id=novel.id, chapter_idx=0,
                      user_id=users["owner"].id, body="note to self")
    job = ImportJob(user_id=users["owner"].id, novel_id=novel.id, status="done")
    s.add_all([term, flag, review, comment, job])
    s.flush()
    set_cover(s, novel.id, data=b"abc", width=1, height=2)
    s.commit()
    return SimpleNamespace(
        s=s, novel=novel.id, term=term.id, flag=flag.id, review=review.id,
        comment=comment.id, job=job.id,
        users={k: SimpleNamespace(id=u.id, email=u.email, is_admin=u.is_admin,
                                  display_name=None)
               for k, u in users.items()},
    )


def _act_as(users, actor):
    user = None if actor == "anon" else users[actor]
    app.dependency_overrides[current_user_optional] = lambda: user

    def need():
        if user is None:
            raise HTTPException(401, "Sign in required.")
        return user

    app.dependency_overrides[current_user] = need


@pytest.fixture
def client(monkeypatch):
    import app.api.novels as novels
    import app.api.reader as reader
    import app.api.translate as translate

    async def fake_embed(novel_id, chaps):
        return 0

    async def fake_title(llm, title, glossary, *a, **k):
        return "Secret"

    async def fake_check(novel_id):
        return SimpleNamespace(added=0, embedded=True)

    async def fake_answer(**kw):
        return SimpleNamespace(answer="a", hits=[])

    async def fake_graph(**kw):
        return SimpleNamespace(
            error=None, lost_race=False, translation="x", new_terms=[],
            critic_passes=0, title_en=None,
        )

    async def fake_step(**kw):
        return SimpleNamespace(
            error=None, chapter_idx=kw["chapter_idx"], pieces_done=1,
            pieces_total=1, complete=True, stalled=False, new_terms=[],
            title_en=None,
        )

    monkeypatch.setattr(novels, "embed_chapters", fake_embed)
    monkeypatch.setattr(novels, "translate_title", fake_title)
    monkeypatch.setattr(novels, "check_novel_updates", fake_check)
    monkeypatch.setattr(reader, "answer_question", fake_answer)
    monkeypatch.setattr(translate, "run_translation_graph", fake_graph)
    monkeypatch.setattr(translate, "translate_step", fake_step)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- the matrix ------------------------------------------------------------

@dataclass(frozen=True)
class R:
    method: str
    path: str  # may use {n} {t} {f} {r} {c}
    ok: tuple = (200,)  # statuses a permitted caller may get
    admin_only: bool = False
    json: object = None
    files: object = None
    headers: object = None
    id: str = ""


ROUTES = [
    R("GET", "/novels/{n}"),
    R("PATCH", "/novels/{n}", json={"title": "x"}, admin_only=True),
    R("PATCH", "/novels/{n}/glossary/{t}", json={"target_term": "Lin2"},
      admin_only=True),
    R("GET", "/novels/{n}/cover"),
    R("PUT", "/novels/{n}/cover", ok=(400,), admin_only=True,
      files={"file": ("a.png", b"not an image", "image/png")}),
    R("DELETE", "/novels/{n}/cover", admin_only=True),
    R("GET", "/novels/{n}/chapters"),
    R("GET", "/novels/{n}/chapters/0"),
    R("POST", "/novels/{n}/titles/translate", admin_only=True, headers=KEY),
    R("POST", "/novels/{n}/check-updates", admin_only=True),
    R("POST", "/novels/embed", json={"novel_id": "{n}"}),
    R("POST", "/ask", json={"novel_id": "{n}", "question": "q"}, headers=KEY),
    R("GET", "/novels/{n}/glossary"),
    R("GET", "/novels/{n}/kg"),
    R("GET", "/novels/{n}/flags"),
    R("POST", "/flags/{f}/resolve", admin_only=True),
    R("GET", "/progress?novel_id={n}"),
    R("POST", "/progress", json={"novel_id": "{n}", "current_chapter": 1}),
    R("POST", "/translate", json={"novel_id": "{n}", "chapter_idx": 0},
      headers=KEY),
    R("POST", "/translate/batch", json={"novel_id": "{n}", "limit": 1},
      headers=KEY),
    R("POST", "/translate/step", json={"novel_id": "{n}", "chapter_idx": 0},
      headers=KEY),
    R("GET", "/novels/{n}/reviews"),
    R("GET", "/novels/{n}/rating"),
    R("PUT", "/novels/{n}/review", json={"rating": 5}, ok=(403,)),
    R("DELETE", "/novels/{n}/review", ok=(204,)),
    R("DELETE", "/reviews/{r}", ok=(204,), admin_only=True),
    R("GET", "/novels/{n}/chapters/0/comments"),
    R("POST", "/novels/{n}/chapters/0/comments", json={"body": "hi"}, ok=(403,)),
    R("DELETE", "/comments/{c}", ok=(204,)),
    R("POST", "/reports", json={"kind": "comment", "target_id": "{c}"}),
    R("GET", "/imports/{j}"),
    R("PUT", "/library/{n}", json={"shelf": "plan"}),
    R("DELETE", "/library/{n}", ok=(204,)),
    # Last: it deletes the book.
    R("DELETE", "/novels/{n}", admin_only=True),
]
for i, r in enumerate(ROUTES):
    object.__setattr__(r, "id", f"{r.method} {r.path}")


def _fill(v, w):
    ids = dict(n=w.novel, t=w.term, f=w.flag, r=w.review, c=w.comment, j=w.job)
    if isinstance(v, str):
        if v.startswith("{") and v.endswith("}") and v[1:-1] in ids:
            return ids[v[1:-1]]
        return v.format(**ids)
    if isinstance(v, dict):
        return {k: _fill(x, w) for k, x in v.items()}
    return v


@pytest.mark.parametrize("actor", ["anon", "other", "owner", "admin"])
@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.id)
def test_private_book_visibility_matrix(client, world, actor, route):
    _act_as(world.users, actor)
    resp = client.request(
        route.method,
        _fill(route.path, world),
        json=_fill(route.json, world),
        files=route.files,
        headers=route.headers,
    )
    code = resp.status_code
    msg = f"{actor} {route.method} {route.path} -> {code} {resp.text[:200]}"
    if actor == "anon":
        assert code in (401, 404), msg  # never a success, never a 403
    elif actor == "other":
        assert code == (403 if route.admin_only else 404), msg
    elif actor == "owner":
        if route.admin_only:
            assert code == 403, msg
        else:
            assert code in route.ok, msg
    else:
        assert code in route.ok, msg


def test_anonymous_reads_match_missing_novel(client, world):
    """A hidden book is indistinguishable from one that does not exist."""
    _act_as(world.users, "other")
    hidden = client.get(f"/novels/{world.novel}")
    missing = client.get("/novels/999999")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_every_novel_id_route_is_in_the_matrix():
    """Fail when a new route taking a novel id (or a comment/review/flag id)
    is added without a matrix entry."""
    import re

    covered = set()
    for r in ROUTES:
        covered.add((r.method, re.sub(r"\?.*", "", r.path)))
    # Takes no existing novel (it creates one); its rules live in test_toc_import.py.
    covered.add(("POST", "/novels/ingest/toc"))
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not (
            "{novel_id}" in path or "{comment_id}" in path
            or "{review_id}" in path or "{flag_id}" in path or "{job_id}" in path
            or path in {"/ask", "/progress", "/translate", "/translate/batch",
                        "/translate/step", "/novels/embed", "/reports",
                        "/novels/ingest/toc"}
        ):
            continue
        norm = (
            path.replace("{novel_id}", "{n}").replace("{term_id}", "{t}")
            .replace("{flag_id}", "{f}").replace("{review_id}", "{r}")
            .replace("{comment_id}", "{c}").replace("{job_id}", "{j}").replace("{idx}", "0")
        )
        for m in route.methods - {"HEAD", "OPTIONS"}:
            if (m, norm) not in covered:
                missing.append((m, norm))
    assert not missing, f"routes missing from the visibility matrix: {missing}"


# --- catalog, rankings, views, library --------------------------------------

def _public_novel(s, title="Open", owner=None):
    from app.storage.models import Chapter, Novel

    n = Novel(title=title, source_lang="zh", owner_id=owner)
    s.add(n)
    s.flush()
    s.add(Chapter(novel_id=n.id, idx=0, title="c", source_text="你好" * 10,
                  char_count=20))
    s.commit()
    return n.id


def _ids(resp):
    assert resp.status_code == 200, resp.text
    return [b["id"] for b in resp.json()]


def test_catalog_hides_private_except_from_owner(client, world):
    pub = _public_novel(world.s)
    for actor, expect_private in (
        ("anon", False), ("other", False), ("owner", True), ("admin", False),
    ):
        _act_as(world.users, actor)
        ids = _ids(client.get("/novels"))
        assert pub in ids
        assert (world.novel in ids) is expect_private, actor


def test_catalog_mine_filter(client, world):
    from app.storage.models import Novel

    pub = _public_novel(world.s)
    _act_as(world.users, "owner")
    assert _ids(client.get("/novels?mine=true")) == [world.novel]
    _act_as(world.users, "other")
    assert _ids(client.get("/novels?mine=true")) == []
    _act_as(world.users, "anon")
    assert _ids(client.get("/novels?mine=true")) == []
    # Filters and search compose with visibility.
    _act_as(world.users, "owner")
    assert world.novel in _ids(client.get("/novels?q=Secret"))
    _act_as(world.users, "other")
    assert _ids(client.get("/novels?q=Secret")) == []
    assert Novel and pub


def test_rankings_exclude_private(client, world):
    from app.storage.models import NovelDailyStat

    pub = _public_novel(world.s)
    for nid, views in ((world.novel, 99), (pub, 1)):
        world.s.add(NovelDailyStat(novel_id=nid, day=date.today(), views=views,
                                   readers=views))
    world.s.commit()
    for actor in ("anon", "owner", "admin"):
        _act_as(world.users, actor)
        r = client.get("/rankings?period=all&limit=1")
        assert [b["id"] for b in r.json()] == [pub], actor


def test_private_reads_are_not_counted_public_are(client, world):
    from sqlalchemy import select

    from app.storage.models import NovelDailyStat

    pub = _public_novel(world.s)
    _act_as(world.users, "owner")
    assert client.get(f"/novels/{world.novel}/chapters/0").status_code == 200
    assert client.get(f"/novels/{pub}/chapters/0").status_code == 200
    world.s.expire_all()
    counted = {
        r.novel_id for r in world.s.scalars(select(NovelDailyStat)).all()
    }
    assert counted == {pub}


def test_shelf_hides_book_that_became_private(client, world):
    pub = _public_novel(world.s)
    _act_as(world.users, "other")
    assert client.put(f"/library/{pub}", json={"shelf": "plan"}).status_code == 200
    lib = client.get("/library").json()
    assert [b["id"] for b in lib["plan"]] == [pub]
    from app.storage.models import Novel

    world.s.get(Novel, pub).visibility = "private"
    world.s.commit()
    assert client.get("/library").json()["plan"] == []


def test_admin_publish_and_unpublish(client, world):
    _act_as(world.users, "other")
    assert client.get(f"/novels/{world.novel}").status_code == 404
    _act_as(world.users, "admin")
    r = client.patch(f"/novels/{world.novel}", json={"visibility": "public"})
    assert r.status_code == 200 and r.json()["visibility"] == "public"
    _act_as(world.users, "other")
    assert client.get(f"/novels/{world.novel}").status_code == 200
    assert world.novel in _ids(client.get("/novels"))
    _act_as(world.users, "admin")
    r = client.patch(f"/novels/{world.novel}", json={"visibility": "private"})
    assert r.json()["visibility"] == "private"
    _act_as(world.users, "other")
    assert client.get(f"/novels/{world.novel}").status_code == 404
    _act_as(world.users, "owner")
    assert client.patch(
        f"/novels/{world.novel}", json={"visibility": "public"}
    ).status_code == 403
    _act_as(world.users, "admin")
    assert client.patch(
        f"/novels/{world.novel}", json={"visibility": "secret"}
    ).status_code == 422


def test_public_books_still_take_reviews_and_comments(client, world):
    pub = _public_novel(world.s)
    _act_as(world.users, "other")
    assert client.put(f"/novels/{pub}/review", json={"rating": 5}).status_code == 200
    assert client.post(
        f"/novels/{pub}/chapters/0/comments", json={"body": "hi"}
    ).status_code == 201
    assert client.get(f"/novels/{pub}/rating").json()["count"] == 1


def test_report_on_private_comment_hidden_from_others(client, world):
    _act_as(world.users, "other")
    r = client.post("/reports", json={"kind": "review", "target_id": world.review})
    assert r.status_code == 404


# --- imports -----------------------------------------------------------------

def _import(client, title="Mine", **extra):
    return client.post(
        "/novels/ingest/text",
        json={"title": title, "text": "第一章\n" + "你好世界。" * 30, **extra},
    )


def test_non_admin_import_is_private_and_owned(client, world):
    from app.storage.models import Novel

    _act_as(world.users, "other")
    r = _import(client)
    assert r.status_code == 200, r.text
    n = world.s.get(Novel, r.json()["novel_id"])
    assert (n.visibility, n.owner_id) == ("private", world.users["other"].id)
    _act_as(world.users, "anon")
    assert client.get(f"/novels/{n.id}").status_code == 404


def test_non_admin_cannot_import_public(client, world):
    _act_as(world.users, "other")
    assert _import(client, visibility="public").status_code == 403
    assert _import(client, visibility="private").status_code == 200


def test_admin_import_defaults_public_and_can_be_private(client, world):
    from app.storage.models import Novel

    _act_as(world.users, "admin")
    a = world.s.get(Novel, _import(client).json()["novel_id"])
    b = world.s.get(Novel, _import(client, "P", visibility="private").json()["novel_id"])
    assert (a.visibility, a.owner_id) == ("public", world.users["admin"].id)
    assert b.visibility == "private"


def test_upload_import_is_private_for_non_admin(client, world):
    from app.storage.models import Novel

    _act_as(world.users, "other")
    r = client.post(
        "/novels/upload",
        files={"file": ("b.txt", ("第一章\n" + "你好世界。" * 30).encode(), "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert world.s.get(Novel, r.json()["novel_id"]).visibility == "private"
    r = client.post(
        "/novels/upload",
        files={"file": ("b.txt", b"x" * 50, "text/plain")},
        data={"visibility": "public"},
    )
    assert r.status_code == 403


def test_deleting_owner_keeps_the_book_ownerless(world):
    from app.storage.models import Novel, User

    world.s.delete(world.s.get(User, world.users["owner"].id))
    world.s.commit()
    world.s.expire_all()
    n = world.s.get(Novel, world.novel)
    assert n.owner_id is None and n.visibility == "private"
