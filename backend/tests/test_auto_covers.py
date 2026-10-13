"""Automatic covers: page image discovery, Wikidata, SSRF guard, backfill.

All HTTP goes through the scraper's injectable MockTransport; DNS is faked.
"""
from __future__ import annotations

import io
import json
import socket

import httpx
import pytest
from PIL import Image

from app.common.config import settings
from app.ingest import cover_fetch, scraper
from app.ingest.cover_fetch import extract_cover_url

BASE = "https://books.example/b/1/"


def _png(w=300, h=450) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


_real_getaddrinfo = socket.getaddrinfo


def _fake_dns(host, *a, **k):
    """Test hosts resolve to a public IP (internal.example to loopback); real
    names such as the database's ``localhost`` still resolve normally."""
    if host == "internal.example":
        return [(2, 1, 6, "", ("127.0.0.1", 80))]
    if host.endswith((".example", ".org")) or host.endswith(".wikimedia.org"):
        return [(2, 1, 6, "", ("93.184.216.34", 443))]
    return _real_getaddrinfo(host, *a, **k)


@pytest.fixture(autouse=True)
def _net(monkeypatch):
    monkeypatch.setattr(settings, "auto_covers", True)
    monkeypatch.setattr(settings, "scraper_backend", "http")
    monkeypatch.setattr(scraper.socket, "getaddrinfo", _fake_dns)


def _serve(monkeypatch, routes: dict):
    """routes: {(host, path-prefix): Response | callable(req)}."""
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        host = req.headers["host"]
        seen.append((host, req.url.path, dict(req.url.params)))
        for (h, prefix), resp in routes.items():
            if host == h and req.url.path.startswith(prefix):
                return resp(req) if callable(resp) else resp
        return httpx.Response(404)

    monkeypatch.setattr(scraper, "_transport", httpx.MockTransport(handler))
    return seen


# --- discovery -----------------------------------------------------------------

def test_extract_prefers_og_then_twitter_then_large_img():
    og = '<meta property="og:image" content="/c/og.jpg"><meta name="twitter:image" content="/t.jpg">'
    assert extract_cover_url(og, BASE) == "https://books.example/c/og.jpg"
    tw = '<meta name="twitter:image" content="https://cdn.example/t.jpg">'
    assert extract_cover_url(tw, BASE) == "https://cdn.example/t.jpg"
    imgs = (
        '<img src="/icon.png" width="32" height="32">'
        '<img src="/logo-no-size.png">'
        '<img src="cover.jpg" width="240" height="320">'
    )
    assert extract_cover_url(imgs, BASE) == "https://books.example/b/1/cover.jpg"
    assert extract_cover_url("<p>nothing</p>", BASE) is None
    assert extract_cover_url('<meta property="og:image" content="data:image/png;base64,AA">', BASE) is None
    assert extract_cover_url('<meta property="og:image" content="javascript:x">', BASE) is None


# --- storing -------------------------------------------------------------------

@pytest.mark.db
async def test_page_og_image_becomes_cover(db_session, monkeypatch):
    from app.storage.models import Novel, NovelCover

    n = Novel(title="B", source_lang="zh")
    db_session.add(n)
    db_session.commit()
    seen = _serve(monkeypatch, {
        ("books.example", "/b/1"): httpx.Response(
            200, text='<meta property="og:image" content="/c.png"><p>x</p>',
            headers={"content-type": "text/html"}),
        ("books.example", "/c.png"): httpx.Response(
            200, content=_png(), headers={"content-type": "image/png"}),
    })
    assert await cover_fetch.auto_cover(n.id, page_urls=[BASE]) is True
    db_session.expire_all()
    row = db_session.get(NovelCover, n.id)
    assert row.content_type == "image/webp" and row.data[:4] == b"RIFF"
    assert [p for _, p, _ in seen] == ["/b/1/", "/c.png"]
    # A second attempt leaves the existing cover alone.
    assert await cover_fetch.auto_cover(n.id, page_urls=[BASE]) is False


@pytest.mark.db
async def test_bad_images_and_unsafe_urls_never_raise(db_session, monkeypatch):
    from app.storage.models import Novel, NovelCover

    n = Novel(title="B", source_lang="zh")
    db_session.add(n)
    db_session.commit()
    seen = _serve(monkeypatch, {
        ("books.example", "/junk"): httpx.Response(200, content=b"<html>not an image"),
        ("books.example", "/boom"): httpx.Response(500),
    })
    assert not await cover_fetch.auto_cover(
        n.id, image_urls=["https://books.example/junk", "https://books.example/boom"])
    # Private addresses are refused before any request is made.
    before = len(seen)
    assert not await cover_fetch.auto_cover(
        n.id, image_urls=["http://internal.example/c.png"], page_urls=["http://internal.example/"])
    assert not await cover_fetch.auto_cover(n.id, image_urls=["http://169.254.169.254/x"])
    assert len(seen) == before
    db_session.expire_all()
    assert db_session.get(NovelCover, n.id) is None


async def test_disabled_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "auto_covers", False)
    seen = _serve(monkeypatch, {})
    assert not await cover_fetch.auto_cover(1, page_urls=[BASE], wikidata_title="x")
    assert seen == []


# --- Wikidata ---------------------------------------------------------------------

def _wikidata_routes(*, with_image=True):
    def api(req):
        p = req.url.params
        if p["action"] == "wbsearchentities":
            assert p["search"] == "西游记" and p["language"] == "zh"
            return httpx.Response(200, json={"search": [{"id": "Q1"}, {"id": "Q2"}]})
        assert p["action"] == "wbgetentities" and p["ids"] == "Q1|Q2"
        claims = {"P18": [{"mainsnak": {"datavalue": {"value": "Xi You Ji.jpg"}}}]}
        return httpx.Response(200, json={"entities": {
            "Q1": {"claims": {}},
            "Q2": {"claims": claims if with_image else {}},
        }})

    return {
        ("www.wikidata.org", "/w/api.php"): api,
        ("commons.wikimedia.org", "/wiki/Special:FilePath/Xi_You_Ji.jpg"): lambda req: httpx.Response(
            302, headers={"location": "https://upload.wikimedia.org/x/Xi_You_Ji.jpg"}),
        ("upload.wikimedia.org", "/x/"): httpx.Response(
            200, content=_png(), headers={"content-type": "image/png"}),
    }


@pytest.mark.db
async def test_wikidata_cover_for_seed_classic(db_session, monkeypatch):
    from app.storage.models import Novel, NovelCover

    n = Novel(title="西游记", source_lang="zh", owner_id=None)
    db_session.add(n)
    db_session.commit()
    seen = _serve(monkeypatch, _wikidata_routes())
    assert await cover_fetch.wikidata_cover_url("西游记") == (
        "https://commons.wikimedia.org/wiki/Special:FilePath/Xi_You_Ji.jpg?width=600")
    assert await cover_fetch.auto_cover(n.id, wikidata_title="西游记") is True
    db_session.expire_all()
    assert db_session.get(NovelCover, n.id) is not None
    assert any(h == "commons.wikimedia.org" and q.get("width") == "600" for h, _, q in seen)


async def test_wikidata_without_image_gives_none(monkeypatch):
    _serve(monkeypatch, _wikidata_routes(with_image=False))
    assert await cover_fetch.wikidata_cover_url("西游记") is None


# --- backfill -------------------------------------------------------------------------

@pytest.mark.db
async def test_fill_covers_backfills_only_books_without(db_session, monkeypatch):
    from app.scripts import fill_covers
    from app.storage.models import Novel, NovelCover
    from app.storage.repository import set_cover

    web = Novel(title="Web", source_lang="zh", owner_id=None,
                source_index_url="https://books.example/b/1/")
    seed = Novel(title="西游记", source_lang="zh", owner_id=None,
                 source_url="https://zh.wikisource.org/wiki/西遊記")
    has = Novel(title="Has", source_lang="zh")
    db_session.add_all([web, seed, has])
    db_session.flush()
    set_cover(db_session, has.id, data=b"abc", width=1, height=1)
    db_session.commit()

    routes = _wikidata_routes()
    routes[("books.example", "/b/1")] = httpx.Response(
        200, text='<meta property="og:image" content="https://books.example/c.png">',
        headers={"content-type": "text/html"})
    routes[("books.example", "/c.png")] = httpx.Response(
        200, content=_png(), headers={"content-type": "image/png"})
    seen = _serve(monkeypatch, routes)

    assert [b[0] for b in fill_covers.books_without_cover()] == [web.id, seed.id]
    got = await fill_covers.fill_covers()
    assert got == {web.id: "Web", seed.id: "西游记"}
    # The Wikisource page itself is never scraped for a (generic) og:image.
    assert not any(h == "zh.wikisource.org" for h, _, _ in seen)
    db_session.expire_all()
    assert db_session.get(NovelCover, has.id).data == b"abc"
    assert fill_covers.books_without_cover() == []


def test_ingest_url_passes_cover_hints_and_survives(db_session, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.auth.deps import current_user
    from app.ingest.scraper import ScrapedPage
    from app.main import app
    from app.storage.models import User

    owner = User(email="own@x.com", password_hash="x")
    db_session.add(owner)
    db_session.commit()
    calls = []

    async def fake_scrape(urls, concurrency=3):
        return [ScrapedPage(url=u, title=None, text="Chapter 1\nbody text here.",
                            cover_url="https://books.example/hint.jpg") for u in urls]

    monkeypatch.setattr("app.api.novels.scrape_many", fake_scrape)
    monkeypatch.setattr(
        "app.api.novels.spawn_auto_cover", lambda nid, **k: calls.append((nid, k))
    )
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=owner.id, email="o@x", is_admin=False
    )
    try:
        with TestClient(app) as c:
            r = c.post("/novels/ingest/url", json={
                "title": "t", "urls": ["https://books.example/b/1/1.html"],
                "index_url": BASE})
        assert r.status_code == 200, r.text
    finally:
        app.dependency_overrides.clear()
    assert calls == [(r.json()["novel_id"], {
        "page_urls": [BASE], "image_urls": ["https://books.example/hint.jpg"]})]
    json.dumps(calls[0][1])
