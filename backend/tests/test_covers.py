"""Cover processing, EPUB cover extraction and the cover routes."""
import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.auth.deps import current_user, current_user_optional, require_admin
from app.ingest.covers import CoverError, process_cover
from app.ingest.epub_loader import load_epub_with_cover
from app.main import app


def _img(fmt="PNG", size=(800, 1200), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


# --- image processing ------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF"])
async def test_valid_formats_become_bounded_webp(fmt):
    out = await process_cover(_img(fmt))
    assert out.content_type == "image/webp"
    assert out.data[:4] == b"RIFF" and out.data[8:12] == b"WEBP"
    assert out.width <= 600 and out.height <= 900
    assert out.width * 3 == out.height * 2 or abs(out.width / out.height - 2 / 3) < 0.01
    assert len(out.data) < 300 * 1024


@pytest.mark.asyncio
async def test_small_image_not_upscaled():
    out = await process_cover(_img(size=(100, 150)))
    assert (out.width, out.height) == (100, 150)


@pytest.mark.asyncio
async def test_metadata_stripped():
    img = Image.new("RGB", (50, 50), "blue")
    exif = Image.Exif()
    exif[0x010E] = "secret description"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    out = await process_cover(buf.getvalue())
    assert b"secret description" not in out.data
    assert not Image.open(io.BytesIO(out.data)).info.get("exif")


@pytest.mark.asyncio
async def test_rejects_too_many_pixels():
    # 7000x6000 = 42 MP, compresses to almost nothing.
    with pytest.raises(CoverError, match="dimensions"):
        await process_cover(_img(size=(7000, 6000)))


@pytest.mark.asyncio
async def test_rejects_oversized_bytes():
    with pytest.raises(CoverError, match="5 MB"):
        await process_cover(b"\x00" * (5 * 1024 * 1024 + 1))


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b"", b"\x89PNG\r\n\x1a\nnot really", b"hello, I am text"])
async def test_rejects_corrupt_and_text(raw):
    with pytest.raises(CoverError):
        await process_cover(raw)


@pytest.mark.asyncio
async def test_rejects_disallowed_real_format():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buf, format="BMP")
    with pytest.raises(CoverError, match="unsupported"):
        await process_cover(buf.getvalue())


# --- EPUB ------------------------------------------------------------------

def _epub(path, *, with_cover=True, opf_cover=True):
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("id1")
    book.set_title("T")
    book.set_language("en")
    c1 = epub.EpubHtml(title="c1", file_name="c1.xhtml", lang="en")
    c1.content = "<html><body><p>Chapter one text.</p></body></html>"
    book.add_item(c1)
    if with_cover:
        if opf_cover:
            book.set_cover("cover.png", _img(size=(120, 180)))
        else:
            book.add_item(epub.EpubItem(
                uid="pic", file_name="img/a.png", media_type="image/png",
                content=_img(size=(60, 90)),
            ))
    book.spine = [c1]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


@pytest.mark.parametrize("opf_cover", [True, False])
def test_epub_cover_extracted(tmp_path, opf_cover):
    p = tmp_path / "b.epub"
    _epub(p, opf_cover=opf_cover)
    text, cover = load_epub_with_cover(p)
    assert "Chapter one text." in text
    assert cover is not None
    assert Image.open(io.BytesIO(cover)).format == "PNG"


def test_epub_without_cover(tmp_path):
    p = tmp_path / "b.epub"
    _epub(p, with_cover=False)
    text, cover = load_epub_with_cover(p)
    assert "Chapter one text." in text and cover is None


# --- routes (need Postgres) ------------------------------------------------

@pytest.fixture
def client():
    admin = SimpleNamespace(id=1, is_admin=True)
    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[current_user_optional] = lambda: admin
    app.dependency_overrides[require_admin] = lambda: admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def novel_id(db_session):
    from app.storage.models import Novel

    n = Novel(title="n", source_lang="zh")
    db_session.add(n)
    db_session.commit()
    return n.id


@pytest.mark.db
def test_cover_roundtrip_etag_and_delete(client, novel_id):
    assert client.get(f"/novels/{novel_id}/cover").status_code == 404
    assert client.get(f"/novels/{novel_id}").json()["has_cover"] is False

    r = client.put(
        f"/novels/{novel_id}/cover",
        files={"file": ("x.png", _img(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_cover"] is True and body["cover_version"]

    g = client.get(f"/novels/{novel_id}/cover")
    assert g.status_code == 200
    assert g.headers["content-type"] == "image/webp"
    assert g.headers["cache-control"] == "public, max-age=86400"
    etag = g.headers["etag"]
    assert etag.strip('"') == body["cover_version"]
    assert Image.open(io.BytesIO(g.content)).format == "WEBP"

    nm = client.get(f"/novels/{novel_id}/cover", headers={"If-None-Match": etag})
    assert nm.status_code == 304 and nm.content == b""

    assert [n for n in client.get("/novels").json() if n["id"] == novel_id][0]["has_cover"]

    assert client.delete(f"/novels/{novel_id}/cover").status_code == 200
    assert client.get(f"/novels/{novel_id}/cover").status_code == 404
    assert client.delete(f"/novels/{novel_id}/cover").status_code == 404


@pytest.mark.db
def test_cover_rejects_bad_uploads(client, novel_id):
    r = client.put(
        f"/novels/{novel_id}/cover",
        files={"file": ("fake.png", b"just some text", "image/png")},
    )
    assert r.status_code == 400
    r = client.put(
        f"/novels/{novel_id}/cover",
        files={"file": ("big.png", _img(size=(7000, 6000)), "image/png")},
    )
    assert r.status_code == 400
    r = client.put(f"/novels/{novel_id}/cover", files={"other": ("a", b"x")})
    assert r.status_code == 422
    assert client.put(
        "/novels/999999/cover", files={"file": ("x.png", _img(), "image/png")}
    ).status_code == 404


@pytest.mark.db
def test_cover_url_is_ssrf_guarded_and_fetches(client, novel_id, monkeypatch):
    r = client.put(f"/novels/{novel_id}/cover", json={"url": "http://127.0.0.1/a.png"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "unsafe_url"

    import app.api.novels as novels

    async def fake(url, max_bytes):
        return _img("JPEG")

    monkeypatch.setattr(novels, "fetch_bytes_guarded", fake)
    r = client.put(f"/novels/{novel_id}/cover", json={"url": "https://example.com/a.jpg"})
    assert r.status_code == 200 and r.json()["has_cover"] is True


@pytest.mark.db
def test_epub_upload_stores_cover(client, db_session, tmp_path):
    p = tmp_path / "b.epub"
    _epub(p)
    r = client.post(
        "/novels/upload",
        files={"file": ("b.epub", p.read_bytes(), "application/epub+zip")},
    )
    assert r.status_code == 200, r.text
    nid = r.json()["novel_id"]
    assert client.get(f"/novels/{nid}/cover").status_code == 200


@pytest.mark.db
def test_cover_storage_cascade(db_session):
    from app.storage.models import Novel, NovelCover
    from app.storage.repository import (
        cover_version, delete_novel, get_cover, set_cover,
    )

    n = Novel(title="n", source_lang="zh")
    db_session.add(n)
    db_session.flush()
    row = set_cover(db_session, n.id, data=b"abc", width=1, height=2)
    v1 = cover_version(n.id, row.updated_at)
    row = set_cover(db_session, n.id, data=b"abcd", width=1, height=2)
    assert get_cover(db_session, n.id).data == b"abcd"
    assert cover_version(n.id, row.updated_at) != v1
    assert delete_novel(db_session, n.id)
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(NovelCover, n.id) is None
