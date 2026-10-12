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
def test_only_stale_foreign_boot_jobs_fail_at_startup(db_session, world):
    from datetime import datetime, timedelta, timezone

    from app.storage.models import ImportJob

    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    uid = world["user"].id
    stale = ImportJob(user_id=uid, status="running", boot_id="other", updated_at=old)
    legacy = ImportJob(user_id=uid, status="queued", boot_id=None, updated_at=old)
    fresh = ImportJob(user_id=uid, status="running", boot_id="other")
    mine = ImportJob(user_id=uid, status="running", boot_id=toc_import.BOOT_ID, updated_at=old)
    done = ImportJob(user_id=uid, status="done", boot_id="other", updated_at=old)
    db_session.add_all([stale, legacy, fresh, mine, done])
    db_session.commit()
    assert toc_import.mark_interrupted_jobs() == 2
    db_session.expire_all()
    assert (stale.status, stale.error) == ("failed", "server restarted")
    assert legacy.status == "failed"
    assert (fresh.status, mine.status, done.status) == ("running", "running", "done")


@pytest.mark.db
def test_per_user_cap_is_race_free(db_session, world):
    import threading

    results = []

    def go(n):
        try:
            toc_import.create_job_and_novel(
                user_id=world["user"].id, title=f"B{n}", lang="zh",
                index_url="https://x.example/", visibility="private", total=1,
            )
            results.append("ok")
        except toc_import.TooManyJobs:
            results.append("429")

    threads = [threading.Thread(target=go, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["429"] * 6 + ["ok"] * 2


@pytest.mark.db
def test_jobs_run_at_most_two_at_a_time(db_session, world, monkeypatch):
    import asyncio

    from app.storage.models import ImportJob

    state = {"now": 0, "max": 0}

    async def slow_scrape(url):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.05)
        state["now"] -= 1
        return ScrapedPage(url=url, title="t", text="正文")

    async def no_embed(novel_id, chaps):
        return 0

    monkeypatch.setattr(toc_import, "scrape_url", slow_scrape)
    monkeypatch.setattr(toc_import, "embed_chapters", no_embed)
    monkeypatch.setattr(toc_import, "REQUEST_DELAY", 0)
    jobs = []
    for name in ("user", "other", "admin"):
        for _ in range(2):
            jobs.append(toc_import.create_job_and_novel(
                user_id=world[name].id, title=name, lang="zh",
                index_url="https://x.example/", visibility="private", total=1,
            ) if name != "admin" else (None, None))
    jobs = [j for j in jobs if j[0]]

    async def main():
        await asyncio.gather(*[
            toc_import.run_job(j, n, [f"https://x.example/{j}.html"]) for j, n in jobs
        ])

    asyncio.run(main())
    assert state["max"] == 2
    db_session.expire_all()
    assert {db_session.get(ImportJob, j).status for j, _ in jobs} == {"done"}


@pytest.mark.db
def test_failure_stores_generic_error_and_terminal_status(db_session, world, monkeypatch):
    import asyncio

    from app.storage.models import ImportJob

    def make():
        return toc_import.create_job_and_novel(
            user_id=world["user"].id, title="t", lang="zh",
            index_url="https://x.example/", visibility="private", total=1,
        )

    j1, n1 = make()
    ok = ScrapedPage(url="https://x.example/1", title="t", text="正文")

    async def fine(url):
        return ok

    async def bad_embed(novel_id, chaps):
        raise RuntimeError("qdrant at 10.0.0.9 refused secret-token")

    monkeypatch.setattr(toc_import, "scrape_url", fine)
    monkeypatch.setattr(toc_import, "embed_chapters", bad_embed)
    monkeypatch.setattr(toc_import, "REQUEST_DELAY", 0)
    asyncio.run(toc_import.run_job(j1, n1, ["https://x.example/1"]))
    db_session.expire_all()
    job = db_session.get(ImportJob, j1)
    assert job.status == "done" and job.error == toc_import.EMBED_WARNING

    # Unexpected crash inside the job: generic message, never the exception text.
    db_session.query(ImportJob).delete()
    db_session.commit()
    j2, n2 = make()

    def boom(*a, **k):
        raise RuntimeError("db password=hunter2")

    monkeypatch.setattr(toc_import, "insert_chapter", boom)
    asyncio.run(toc_import.run_job(j2, n2, ["https://x.example/1"]))
    db_session.expire_all()
    job = db_session.get(ImportJob, j2)
    assert job.status == "failed" and job.error == toc_import.GENERIC_ERROR
    assert "hunter2" not in job.error


@pytest.mark.db
def test_timeout_marks_job_failed(db_session, world, monkeypatch):
    import asyncio

    from app.storage.models import ImportJob

    jid, nid = toc_import.create_job_and_novel(
        user_id=world["user"].id, title="t", lang="zh",
        index_url="https://x.example/", visibility="private", total=1,
    )

    async def hang(url):
        await asyncio.sleep(30)

    monkeypatch.setattr(toc_import, "scrape_url", hang)
    monkeypatch.setattr(toc_import, "JOB_TIMEOUT_S", 0.2)
    monkeypatch.setattr(toc_import, "REQUEST_DELAY", 0)
    asyncio.run(toc_import.run_job(jid, nid, ["https://x.example/1"]))
    db_session.expire_all()
    assert db_session.get(ImportJob, jid).status == "failed"


@pytest.mark.db
def test_only_one_process_holds_the_update_leader_lock(db_session):
    from app.ingest.auto_update import release_leader, try_acquire_leader

    first = try_acquire_leader(991)
    assert first is not None
    assert try_acquire_leader(991) is None
    release_leader(first, 991)
    again = try_acquire_leader(991)
    assert again is not None
    release_leader(again, 991)


@pytest.mark.db
def test_seed_skip_only_matches_public_ownerless(db_session, world):
    import asyncio

    from app.scripts import seed_classics
    from app.ingest.wikisource import WORKS
    from app.storage.models import Novel

    work = list(WORKS.values())[0]

    class NoPages:
        async def chapter_pages(self, w):
            return []

    # A private book by a user with the same title must not block the seed.
    db_session.add(Novel(title=work.title, source_lang="zh", visibility="private",
                         owner_id=world["user"].id))
    db_session.commit()
    seen = asyncio.run(seed_classics.seed_work(NoPages(), work, 5))
    assert seen is None  # got past the skip check to "no chapter pages found"

    db_session.add(Novel(title=work.title, source_lang="zh", visibility="public",
                         owner_id=None))
    db_session.commit()
    calls = []

    class Spy:
        async def chapter_pages(self, w):
            calls.append(1)
            return []

    asyncio.run(seed_classics.seed_work(Spy(), work, 5))
    assert calls == []  # skipped: public ownerless copy exists


@pytest.mark.db
def test_toc_import_queues_mt_and_cover_without_blocking(client, world, monkeypatch):
    import app.api.imports as imports
    import app.ingest.cover_fetch as cover_fetch
    import app.mt.job as mt_job

    async def fetch(url):
        return '<meta property="og:image" content="/img/cover.jpg">' + HTML

    queued, covers = [], []
    monkeypatch.setattr(imports, "fetch_html", fetch)
    monkeypatch.setattr(mt_job, "enqueue", lambda nid, **k: queued.append(nid) or True)
    monkeypatch.setattr(
        cover_fetch, "spawn_auto_cover", lambda nid, **k: covers.append((nid, k))
    )
    act_as(world["user"])
    r = client.post("/novels/ingest/toc", json={"index_url": INDEX})
    job = wait_done(client, r.json()["job_id"])
    assert job["status"] == "done"
    assert queued == [job["novel_id"]]
    assert covers == [(job["novel_id"], {
        "image_urls": ["https://novels.example/img/cover.jpg", None]})]


@pytest.mark.db
def test_toc_import_survives_mt_and_cover_errors(client, world, monkeypatch):
    import app.ingest.cover_fetch as cover_fetch
    import app.mt.job as mt_job

    monkeypatch.setattr(mt_job, "ensure_job", lambda n: 1 / 0)
    monkeypatch.setattr(__import__("app.common.config", fromlist=["settings"]).settings, "mt_provider", "google_free")
    monkeypatch.setattr(cover_fetch.settings, "auto_covers", True)
    act_as(world["user"])
    r = client.post("/novels/ingest/toc", json={"index_url": INDEX})
    assert wait_done(client, r.json()["job_id"])["status"] == "done"
