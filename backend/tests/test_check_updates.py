"""Chapter update check: link discovery (no DB) and the route (db marker)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.deps import require_admin
from app.ingest import updates
from app.ingest.scraper import ScrapedPage, UnsafeURL
from app.main import app

INDEX = "https://novels.example/book/1/"
HTML = """
<a href="/">Home</a><a href="/login">Login</a>
<a href="/book/1/c1.html">One</a><a href="c2.html#x">Two</a>
<a href="https://other.example/book/1/c9.html">Offsite</a>
<a href="/book/1/c3.html">Three</a><a href="/book/1/c3.html">Three again</a>
<a href="/book/1/">Self</a><a href="mailto:a@b.c">m</a>
"""


def test_discover_links_filters_and_orders():
    known = ["https://novels.example/book/1/c1.html"]
    assert updates.discover_links(HTML, INDEX, known) == [
        "https://novels.example/book/1/c2.html",
        "https://novels.example/book/1/c3.html",
    ]


def test_discover_links_without_known_uses_index_dir():
    out = updates.discover_links(HTML, INDEX, [])
    assert out[0] == "https://novels.example/book/1/c1.html" and len(out) == 3


@pytest.fixture
def admin_client():
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id=1, email="a@x", is_admin=True
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_check_updates_requires_admin():
    with TestClient(app) as c:
        assert c.post("/novels/1/check-updates").status_code in (401, 403)


@pytest.mark.db
def test_check_updates_appends_only_new(admin_client, db_session, monkeypatch):
    from app.storage.models import Chapter
    from app.storage.repository import create_novel, insert_chapter, update_novel

    n = create_novel(db_session, title="t", source_lang="zh")
    update_novel(db_session, n.id, source_index_url=INDEX)
    for i in (1, 2):
        insert_chapter(
            db_session, novel_id=n.id, idx=i - 1, title=f"c{i}",
            source_text="x", source_url=f"https://novels.example/book/1/c{i}.html",
        )
    db_session.commit()
    nid = n.id

    async def fake_html(url):
        return HTML

    scraped = []

    async def fake_scrape(urls, concurrency=3):
        scraped.extend(urls)
        return [ScrapedPage(url=u, title="T3", text="new text") for u in urls]

    embedded = []

    async def fake_embed(novel_id, chaps):
        embedded.extend(c.idx for c in chaps)
        return len(chaps)

    monkeypatch.setattr(updates, "fetch_html", fake_html)
    monkeypatch.setattr(updates, "scrape_many", fake_scrape)
    monkeypatch.setattr(updates, "embed_chapters", fake_embed)

    r = admin_client.post(f"/novels/{nid}/check-updates")
    assert r.status_code == 200 and r.json() == {"added": 1}
    assert scraped == ["https://novels.example/book/1/c3.html"]
    assert embedded == [2]

    db_session.expire_all()
    rows = db_session.execute(
        select(Chapter.idx, Chapter.source_url).where(Chapter.novel_id == nid).order_by(Chapter.idx)
    ).all()
    assert [r[0] for r in rows] == [0, 1, 2]
    assert rows[2][1].endswith("/c3.html")

    # Second run finds nothing new.
    assert admin_client.post(f"/novels/{nid}/check-updates").json() == {"added": 0}


@pytest.mark.db
def test_check_updates_errors(admin_client, db_session, monkeypatch):
    from app.storage.repository import create_novel, insert_chapter, update_novel

    assert admin_client.post("/novels/99999/check-updates").status_code == 404
    n = create_novel(db_session, title="t", source_lang="zh")
    db_session.commit()
    assert admin_client.post(f"/novels/{n.id}/check-updates").status_code == 409

    update_novel(db_session, n.id, source_index_url="http://127.0.0.1/x/")
    insert_chapter(
        db_session, novel_id=n.id, idx=0, title="c", source_text="x",
        source_url="http://127.0.0.1/x/1",
    )
    db_session.commit()

    async def boom(url):
        raise UnsafeURL("private")

    monkeypatch.setattr(updates, "fetch_html", boom)
    r = admin_client.post(f"/novels/{n.id}/check-updates")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "unsafe_url"
