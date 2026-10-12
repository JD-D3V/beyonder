"""Bulk table-of-contents import: route, background job, limits, restart."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import current_user
from app.ingest import toc_import
from app.ingest.scraper import ScrapedPage, UnsafeURL
from app.main import app

INDEX = "https://novels.example/book/1/"
HTML = (
    "<title>My Book</title>"
    '<a href="/">Home</a><a href="c1.html">1</a><a href="c2.html">2</a>'
    '<a href="c3.html">3</a><a href="https://other.example/book/1/c9.html">x</a>'
)


def test_discover_toc_respects_limit_and_order():
    assert toc_import.discover_toc(HTML, INDEX, 2) == [
        "https://novels.example/book/1/c1.html",
        "https://novels.example/book/1/c2.html",
    ]


@pytest.fixture
def world(db_session):
    from app.storage.models import User

    users = {}
    for name, admin in (("user", False), ("other", False), ("admin", True)):
        u = User(email=f"{name}@x.com", password_hash="x", is_admin=admin)
        db_session.add(u)
        users[name] = u
    db_session.commit()
    return {k: SimpleNamespace(id=u.id, email=u.email, is_admin=u.is_admin)
            for k, u in users.items()}


def act_as(user):
    def need():
        if user is None:
            raise HTTPException(401, "Sign in required.")
        return user
    app.dependency_overrides[current_user] = need


@pytest.fixture
def client(monkeypatch):
    import app.api.imports as imports

    async def fake_fetch(url):
        return HTML

    async def fake_scrape(url):
        if url.endswith("c2.html"):
            raise RuntimeError("boom")  # one bad page is skipped
        return ScrapedPage(url=url, title=f"T {url[-7:-5]}", text="正文" * 10)

    async def fake_embed(novel_id, chaps):
        fake_embed.calls.append((novel_id, len(chaps)))
        return 0

    fake_embed.calls = []
    monkeypatch.setattr(imports, "fetch_html", fake_fetch)
    monkeypatch.setattr(toc_import, "scrape_url", fake_scrape)
    monkeypatch.setattr(toc_import, "embed_chapters", fake_embed)
    monkeypatch.setattr(toc_import, "REQUEST_DELAY", 0)
    with TestClient(app) as c:
        c.embed = fake_embed
        yield c
    app.dependency_overrides.clear()


def wait_done(client, job_id, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/imports/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")




@pytest.mark.db
def test_toc_import_runs_in_background_and_saves_chapters(client, world, db_session):
    from sqlalchemy import select

    from app.storage.models import Chapter, Novel

    act_as(world["user"])
    r = client.post("/novels/ingest/toc", json={"index_url": INDEX})
    assert r.status_code == 202
    job = wait_done(client, r.json()["job_id"])
    assert job["status"] == "done" and job["total"] == 3 and job["done"] == 3
    db_session.expire_all()
    novel = db_session.get(Novel, job["novel_id"])
    assert novel.title == "My Book"
    assert (novel.visibility, novel.owner_id) == ("private", world["user"].id)
    assert novel.source_index_url == INDEX
    chs = db_session.scalars(
        select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.idx)
    ).all()
    assert [(c.idx, c.source_url) for c in chs] == [
        (0, "https://novels.example/book/1/c1.html"),
        (1, "https://novels.example/book/1/c3.html"),
    ]
    assert client.embed.calls == [(novel.id, 2)]


@pytest.mark.db
def test_visibility_rules_and_title_override(client, world, db_session):
    act_as(world["user"])
    r = client.post("/novels/ingest/toc", json={"index_url": INDEX, "visibility": "public"})
    assert r.status_code == 403
    act_as(world["admin"])
    r = client.post("/novels/ingest/toc", json={"index_url": INDEX, "title": "Mine"})
    job = wait_done(client, r.json()["job_id"])
    from app.storage.models import Novel

    db_session.expire_all()
    n = db_session.get(Novel, job["novel_id"])
    assert (n.title, n.visibility) == ("Mine", "public")


@pytest.mark.db
def test_requires_sign_in_and_validates(client, world):
    act_as(None)
    assert client.post("/novels/ingest/toc", json={"index_url": INDEX}).status_code == 401
    act_as(world["user"])
    assert client.post("/novels/ingest/toc", json={"index_url": INDEX, "max_chapters": 501}).status_code == 422
    assert client.post("/novels/ingest/toc", json={"index_url": INDEX, "max_chapters": 0}).status_code == 422


@pytest.mark.db
def test_max_chapters_limits_the_import(client, world):
    act_as(world["user"])
    r = client.post("/novels/ingest/toc", json={"index_url": INDEX, "max_chapters": 1})
    job = wait_done(client, r.json()["job_id"])
    assert job["total"] == 1 and job["done"] == 1


@pytest.mark.db
def test_unsafe_url_and_no_links(client, world, monkeypatch):
    import app.api.imports as imports

    act_as(world["user"])

    async def unsafe(url):
        raise UnsafeURL("private address")

    monkeypatch.setattr(imports, "fetch_html", unsafe)
    r = client.post("/novels/ingest/toc", json={"index_url": "http://127.0.0.1/x/"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "unsafe_url"

    async def bare(url):
        return "<p>nothing here</p>"

    monkeypatch.setattr(imports, "fetch_html", bare)
    assert client.post("/novels/ingest/toc", json={"index_url": INDEX}).status_code == 400


@pytest.mark.db
def test_scrape_goes_through_the_ssrf_guard(client, world, monkeypatch):
    """A chapter link that resolves to a blocked address fails the page, not the server."""
    async def blocked(url):
        raise UnsafeURL("private address")

    monkeypatch.setattr(toc_import, "scrape_url", blocked)
    act_as(world["user"])
    job = wait_done(client, client.post("/novels/ingest/toc", json={"index_url": INDEX}).json()["job_id"])
    assert job["status"] == "failed" and "No chapter text" in job["error"]


@pytest.mark.db
def test_at_most_two_active_jobs_per_user(client, world, db_session):
    from app.storage.models import ImportJob

    for st in ("running", "queued"):
        db_session.add(ImportJob(user_id=world["user"].id, status=st))
    db_session.add(ImportJob(user_id=world["user"].id, status="done"))
    db_session.commit()
    act_as(world["user"])
    assert client.post("/novels/ingest/toc", json={"index_url": INDEX}).status_code == 429
    act_as(world["other"])
    r = client.post("/novels/ingest/toc", json={"index_url": INDEX})
    assert r.status_code == 202
    wait_done(client, r.json()["job_id"])


@pytest.mark.db
def test_job_access_and_listing(client, world, db_session):
    from app.storage.models import ImportJob

    mine = ImportJob(user_id=world["user"].id, status="done")
    theirs = ImportJob(user_id=world["other"].id, status="done")
    db_session.add_all([mine, theirs])
    db_session.commit()
    act_as(world["user"])
    assert client.get(f"/imports/{mine.id}").status_code == 200
    assert client.get(f"/imports/{theirs.id}").status_code == 404
    assert client.get("/imports/99999").status_code == 404
    assert [j["id"] for j in client.get("/imports?mine=true").json()] == [mine.id]
    assert [j["id"] for j in client.get("/imports").json()] == [mine.id]
    act_as(world["admin"])
    assert client.get(f"/imports/{theirs.id}").status_code == 200
    assert {j["id"] for j in client.get("/imports").json()} == {mine.id, theirs.id}
    assert client.get("/imports?mine=true").json() == []
    act_as(None)
    assert client.get(f"/imports/{mine.id}").status_code == 401


@pytest.mark.db
def test_running_jobs_fail_at_startup(db_session, world):
    from app.storage.models import ImportJob

    a = ImportJob(user_id=world["user"].id, status="running")
    b = ImportJob(user_id=world["user"].id, status="done")
    db_session.add_all([a, b])
    db_session.commit()
    assert toc_import.mark_interrupted_jobs() == 1
    db_session.expire_all()
    assert (a.status, a.error, b.status) == ("failed", "server restarted", "done")
