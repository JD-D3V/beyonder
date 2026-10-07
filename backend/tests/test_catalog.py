"""Catalog filters (SQL shape) and library shelf routes."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.auth.deps import current_user, current_user_optional
from app.main import app
from app.storage.repository import CatalogParams, catalog_query


def _sql(**kw):
    stmt = catalog_query(CatalogParams(**kw))
    raw = str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    # The pyformat dialect doubles % and backslashes inside literals; undo it.
    return raw.replace("%%", "%").replace("\\\\", "\\")


def _where(sql):
    """Only the outer WHERE (the aggregate subqueries have their own)."""
    tail = sql.rsplit("= novels.id", 1)[1].split("ORDER BY")[0]
    return tail


def test_catalog_filters_build_expected_sql():
    sql = _sql(
        q="100%_x", tag="Martial Arts", status="ongoing", min_chapters=5,
        max_chapters=50, sort="chapters", limit=10, offset=20,
    )
    where = _where(sql)
    assert "ILIKE" in where and "novels.title" in where and "novels.author" in where
    assert "100\\%\\_x" in where  # wildcard chars escaped
    assert "%,martial arts,%" in where
    assert "novels.status = 'ongoing'" in where
    assert ">= 5" in where and "<= 50" in where
    order = sql.split("ORDER BY")[1]
    assert order.index("chapters") < order.index("novels.id DESC")
    assert "DESC" in order.split("novels.id")[0]
    assert "LIMIT 10" in sql and "OFFSET 20" in sql


def test_no_filters_no_where_and_default_sort():
    sql = _sql()
    assert _where(sql).strip() == ""
    order = sql.split("ORDER BY")[1]
    assert "novels.updated_at DESC" in order and "novels.id DESC" in order


def test_sort_new_uses_created_at():
    assert "novels.created_at DESC" in _sql(sort="new").split("ORDER BY")[1]


def test_tag_is_whole_tag_pattern_not_substring():
    where = _where(_sql(tag="art"))
    assert "%,art,%" in where and "%art%" not in where.replace("%,art,%", "")


class _User:
    id = 7
    email = "u@example.com"
    is_admin = False


@contextmanager
def _fake_session():
    yield object()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.api.library.get_session", _fake_session)
    monkeypatch.setattr("app.api.novels.get_session", _fake_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login():
    app.dependency_overrides[current_user] = lambda: _User()
    app.dependency_overrides[current_user_optional] = lambda: _User()


def test_library_put_rejects_unknown_shelf_422(client):
    _login()
    r = client.put("/library/1", json={"shelf": "bogus"})
    assert r.status_code == 422


def test_library_requires_auth(client):
    assert client.get("/library").status_code == 401
    assert client.put("/library/1", json={"shelf": "plan"}).status_code == 401
    assert client.delete("/library/1").status_code == 401


def test_library_put_unknown_novel_404(client, monkeypatch):
    _login()
    monkeypatch.setattr("app.api.library.get_novel", lambda s, nid: None)
    assert client.put("/library/1", json={"shelf": "plan"}).status_code == 404


def test_library_put_and_delete(client, monkeypatch):
    _login()
    calls = []
    monkeypatch.setattr("app.api.library.get_novel", lambda s, nid: object())
    monkeypatch.setattr(
        "app.api.library.set_shelf",
        lambda s, u, n, sh: calls.append(("set", u, n, sh)),
    )
    monkeypatch.setattr(
        "app.api.library.remove_shelf", lambda s, u, n: calls.append(("del", u, n))
    )
    assert client.put("/library/3", json={"shelf": "reading"}).status_code == 200
    assert client.delete("/library/3").status_code == 204
    assert calls == [("set", 7, 3, "reading"), ("del", 7, 3)]


def test_library_get_groups_shelves(client, monkeypatch):
    _login()
    from app.storage.repository import LibraryRow

    n = SimpleNamespace(
        id=1, title="T", title_en=None, author=None, description=None, tags="a, b",
        status="ongoing", source_lang="zh", source_url=None, updated_at=None,
    )
    row = LibraryRow(novel=n, chapter_count=3, char_count=9, translated_count=1)
    monkeypatch.setattr(
        "app.api.library.shelf_rows", lambda s, uid: [("reading", row, 2)]
    )
    r = client.get("/library")
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == [] and body["completed"] == []
    assert body["reading"][0]["current_chapter"] == 2
    assert body["reading"][0]["tags"] == ["a", "b"]


def test_novels_limit_over_100_is_422(client):
    assert client.get("/novels?limit=101").status_code == 422
    assert client.get("/novels?offset=-1").status_code == 422


def test_upload_pdf_error_is_400(client, monkeypatch):
    _login()

    def boom(p):
        raise ValueError("PDF has no extractable text (scanned?)")

    monkeypatch.setattr("app.api.novels.load_pdf", boom)
    r = client.post(
        "/novels/upload",
        files={"file": ("A.PDF", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 400
    assert "no extractable text" in r.json()["detail"]
