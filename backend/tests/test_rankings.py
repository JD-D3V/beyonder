"""View tracking and rankings: route behaviour, SQL shape, upsert + windows."""
from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.viewstats import ViewerDedupe, track_chapter_view, viewer_key
from app.main import app
from app.storage.repository import (
    CatalogParams, LibraryRow, catalog_query, ranking_query,
)

TODAY = date(2026, 10, 9)


def _sql(stmt):
    return str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _novel(i):
    return SimpleNamespace(
        id=i, title=f"T{i}", title_en=None, author=None, description=None, tags="",
        status="ongoing", source_lang="zh", source_url=None, updated_at=None,
    )


@contextmanager
def _fake_session():
    yield object()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.api.novels.get_session", _fake_session)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_rankings_route_shape(client, monkeypatch):
    seen = {}

    def fake(s, period, limit, today):
        seen.update(period=period, limit=limit)
        return [
            (50, LibraryRow(_novel(4), 3, 9, 1, views_total=80)),
            (7, LibraryRow(_novel(2), 1, 1, 0, views_total=7)),
        ]

    monkeypatch.setattr("app.api.novels.ranked_rows", fake)
    r = client.get("/rankings?period=month&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert seen == {"period": "month", "limit": 5}
    assert [(b["id"], b["rank"], b["views"], b["views_total"]) for b in body] == [
        (4, 1, 50, 80), (2, 2, 7, 7),
    ]


def test_rankings_validates_params(client):
    assert client.get("/rankings?period=year").status_code == 422
    assert client.get("/rankings?limit=0").status_code == 422
    assert client.get("/rankings?limit=101").status_code == 422


def test_sort_views_allowed_and_bogus_rejected(client, monkeypatch):
    monkeypatch.setattr("app.api.novels.library_rows", lambda s, p: [])
    assert client.get("/novels?sort=views").status_code == 200
    assert client.get("/novels?sort=hax").status_code == 422


def test_chapter_view_failure_never_raises():
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="1.2.3.4"))
    track_chapter_view(object(), req, None, 1)  # object() has no begin_nested


def test_viewer_key_never_contains_raw_ip():
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.9"))
    k = viewer_key(req, None, TODAY)
    assert len(k) == 16 and "203" not in k
    assert k != viewer_key(req, None, TODAY + timedelta(days=1))
    assert viewer_key(req, SimpleNamespace(id=5), TODAY) == "u5"


def test_dedupe_bounded_and_daily_reset():
    d = ViewerDedupe(cap=3)
    assert d.first_today(1, "a", TODAY)
    assert not d.first_today(1, "a", TODAY)
    assert d.first_today(1, "b", TODAY) and d.first_today(1, "c", TODAY)
    assert d.first_today(1, "d", TODAY)  # cap hit: reset, still counted
    assert len(d._seen) == 1
    assert d.first_today(1, "d", TODAY + timedelta(days=1))  # new day


def test_ranking_query_sql_shape():
    sql = _sql(ranking_query("week", 20, TODAY))
    assert "sum(novel_daily_stats.views)" in sql
    assert "novel_daily_stats.day > '2026-10-02'" in sql
    order = sql.split("ORDER BY")[1]
    assert order.index("DESC") < order.index("novel_daily_stats.novel_id ASC")
    assert "LIMIT 20" in sql
    assert "novel_daily_stats.day >" not in _sql(ranking_query("all", 5, TODAY))
    assert "'2026-10-08'" in _sql(ranking_query("day", 5, TODAY))


def test_catalog_sort_views_sql():
    sql = _sql(catalog_query(CatalogParams(sort="views")))
    assert "novel_daily_stats" in sql
    assert "DESC" in sql.split("ORDER BY")[1].split("novels.id")[0]


# --- Postgres -------------------------------------------------------------

@pytest.mark.db
def test_upsert_counter(db_session):
    from app.storage.models import Novel, NovelDailyStat
    from app.storage.repository import record_view

    n = Novel(title="n", source_lang="zh")
    db_session.add(n)
    db_session.flush()
    record_view(db_session, n.id, TODAY, new_reader=True)
    record_view(db_session, n.id, TODAY, new_reader=False)
    record_view(db_session, n.id, TODAY, new_reader=True)
    db_session.flush()
    row = db_session.get(NovelDailyStat, (n.id, TODAY))
    db_session.refresh(row)
    assert (row.views, row.readers) == (3, 2)


@pytest.mark.db
def test_ranking_windows_and_totals(db_session):
    from app.storage.models import Novel, NovelDailyStat
    from app.storage.repository import library_rows, ranked_rows

    ns = [Novel(title=f"n{i}", source_lang="zh") for i in range(3)]
    db_session.add_all(ns)
    db_session.flush()
    a, b, c = (n.id for n in ns)
    db_session.add_all([
        NovelDailyStat(novel_id=a, day=TODAY, views=2),
        NovelDailyStat(novel_id=a, day=TODAY - timedelta(days=3), views=5),
        NovelDailyStat(novel_id=b, day=TODAY - timedelta(days=10), views=100),
        NovelDailyStat(novel_id=c, day=TODAY, views=2),
    ])
    db_session.flush()

    def ranked(period, limit=20):
        return [(r.novel.id, v) for v, r in ranked_rows(db_session, period, limit, TODAY)]

    assert ranked("day") == [(a, 2), (c, 2)]  # tie -> lower id first
    assert ranked("week") == [(a, 7), (c, 2)]
    assert ranked("month") == [(b, 100), (a, 7), (c, 2)]
    assert ranked("all", 1) == [(b, 100)]
    totals = {r.novel.id: r.views_total for r in library_rows(db_session)}
    assert totals == {a: 7, b: 100, c: 2}
    by_views = library_rows(db_session, CatalogParams(sort="views"))
    assert [r.novel.id for r in by_views] == [b, a, c]
