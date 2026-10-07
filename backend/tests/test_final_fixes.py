"""Final-review fixes: admin horizon, concurrent-safe glossary/shelf writes,
login throttling, input bounds, 404s, upload off the event loop."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.auth.deps import current_user, current_user_optional
from app.main import app


@contextmanager
def _fake_session():
    yield object()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _as(user):
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_user_optional] = lambda: user


# --- I1: admins see everything by default ---------------------------------


def test_admin_glossary_and_flags_uncapped_without_up_to(client, monkeypatch):
    import app.api.reader as reader

    monkeypatch.setattr(reader, "get_session", _fake_session)
    monkeypatch.setattr(reader, "get_progress", lambda s, u, n: 2)
    seen = {}

    def terms(s, nid, up_to_chapter, target_lang):
        seen["up_to"] = up_to_chapter
        return []

    def mk(i, ch):
        return SimpleNamespace(
            id=i, novel_id=1, chapter_idx=ch, kind="idiom", source_span="",
            target_span="", note="", status="open", created_at=None, resolved_by=None,
        )

    monkeypatch.setattr(reader, "get_terms_for_chapters", terms)
    monkeypatch.setattr(reader, "list_flags", lambda s, n, st, ch: [mk(1, 1), mk(2, 500)])
    _as(SimpleNamespace(id=1, email="a@x", is_admin=True))
    assert client.get("/novels/1/glossary").status_code == 200
    assert seen["up_to"] >= 10**5
    assert [f["id"] for f in client.get("/novels/1/flags").json()] == [1, 2]
    client.get("/novels/1/glossary?up_to=3")
    assert seen["up_to"] == 3  # an explicit horizon is still honoured


# --- I3: on-conflict writes ------------------------------------------------


class _RecSession:
    """Records statements; INSERT ... RETURNING yields a row unless src exists."""

    def __init__(self, existing=()):
        self.existing = set(existing)
        self.sql: list[str] = []

    def execute(self, stmt):
        c = stmt.compile(dialect=postgresql.dialect())
        sql = str(c)
        self.sql.append(sql)
        params = c.params
        if sql.startswith("INSERT"):
            src = params.get("source_term")
            row = None if src in self.existing else SimpleNamespace(source_term=src)
            return SimpleNamespace(scalar_one_or_none=lambda: row)
        return SimpleNamespace(rowcount=1)

    def flush(self):
        pass


def test_insert_seed_terms_uses_on_conflict_and_lowers_first_chapter():
    from app.storage.repository import insert_seed_terms

    s = _RecSession(existing={"师兄"})
    made = insert_seed_terms(s, novel_id=1, entries=[
        {"source_term": "师兄", "target_term": "x", "first_chapter": 0},
        {"source_term": "长老", "target_term": "Elder", "first_chapter": 2},
        {"source_term": "长老", "target_term": "Elder", "first_chapter": 2},
    ])
    assert [t.source_term for t in made] == ["长老"]
    inserts = [q for q in s.sql if q.startswith("INSERT")]
    assert len(inserts) == 2
    assert all("ON CONFLICT ON CONSTRAINT uq_term_novel_src_lang DO NOTHING" in q for q in inserts)
    updates = [q for q in s.sql if q.startswith("UPDATE")]
    # Only the conflicting seed lowers first_chapter; nothing else is touched.
    assert len(updates) == 1
    assert "first_chapter" in updates[0]
    assert "target_term" not in updates[0].split("WHERE")[0]
    assert "locked" not in updates[0]


def test_set_shelf_is_an_upsert():
    from app.storage.repository import set_shelf

    s = _RecSession()
    set_shelf(s, 1, 2, "plan")
    assert len(s.sql) == 1
    assert "ON CONFLICT (user_id, novel_id) DO UPDATE" in s.sql[0]


@pytest.mark.db
def test_seed_terms_conflict_keeps_row_and_takes_min_first_chapter(db_session):
    from app.storage.models import Novel, Term
    from app.storage.repository import insert_seed_terms

    n = Novel(title="n", source_lang="zh")
    db_session.add(n)
    db_session.flush()
    db_session.add(Term(novel_id=n.id, source_term="师兄", target_term="Mine",
                        target_lang="en", confidence=0.1, first_chapter=9, locked=True))
    db_session.flush()
    made = insert_seed_terms(db_session, novel_id=n.id, entries=[
        {"source_term": "师兄", "target_term": "Senior", "first_chapter": 4},
        {"source_term": "长老", "target_term": "Elder", "first_chapter": 2},
    ])
    assert [t.source_term for t in made] == ["长老"] and made[0].id is not None
    t = db_session.query(Term).filter_by(novel_id=n.id, source_term="师兄").one()
    db_session.refresh(t)
    assert (t.target_term, t.locked, t.first_chapter) == ("Mine", True, 4)
    # A later chapter never raises it again.
    insert_seed_terms(db_session, novel_id=n.id, entries=[
        {"source_term": "师兄", "target_term": "Senior", "first_chapter": 7},
    ])
    db_session.refresh(t)
    assert t.first_chapter == 4


@pytest.mark.db
def test_upsert_terms_survives_concurrent_insert(db_session):
    """Simulate losing the race: the select misses, the insert conflicts."""
    from app.storage.models import Novel, Term
    from app.storage.repository import upsert_terms

    n = Novel(title="n", source_lang="zh")
    db_session.add(n)
    db_session.flush()
    db_session.add(Term(novel_id=n.id, source_term="师兄", target_term="Old",
                        target_lang="en", confidence=0.1, first_chapter=5))
    db_session.flush()

    class Racing:
        def __init__(self, s):
            self._s = s
            self._missed = False

        def execute(self, stmt, *a, **k):
            if not self._missed and "SELECT" in str(stmt).upper():
                self._missed = True
                return SimpleNamespace(scalar_one_or_none=lambda: None)
            return self._s.execute(stmt, *a, **k)

        def __getattr__(self, name):
            return getattr(self._s, name)

    created: list = []
    out = upsert_terms(
        Racing(db_session), novel_id=n.id, created_out=created,
        entries=[{"source_term": "师兄", "target_term": "New",
                  "confidence": 0.9, "first_chapter": 2}],
    )
    assert created == []
    t = db_session.query(Term).filter_by(novel_id=n.id, source_term="师兄").one()
    assert out == [t]
    assert (t.target_term, t.first_chapter) == ("New", 2)


@pytest.mark.db
def test_set_shelf_twice_updates(db_session):
    from app.storage.models import LibraryEntry, Novel, User
    from app.storage.repository import set_shelf

    u = User(email="s@example.com", password_hash="x")
    n = Novel(title="n", source_lang="zh")
    db_session.add_all([u, n])
    db_session.flush()
    set_shelf(db_session, u.id, n.id, "plan")
    set_shelf(db_session, u.id, n.id, "reading")
    rows = db_session.query(LibraryEntry).filter_by(user_id=u.id).all()
    assert [r.shelf for r in rows] == ["reading"]


# --- I4: login throttling and hashing off the loop ------------------------


@pytest.fixture
def auth(monkeypatch):
    import app.api.auth_routes as ar

    ar.reset_throttles()

    class _Res:
        def scalar_one_or_none(self):
            return None

    @contextmanager
    def sess():
        yield SimpleNamespace(execute=lambda *a, **k: _Res())

    pooled = []

    async def fake_pool(fn, *a, **k):
        pooled.append(fn.__name__)
        return fn(*a, **k)

    monkeypatch.setattr(ar, "get_session", sess)
    monkeypatch.setattr(ar, "run_in_threadpool", fake_pool)
    monkeypatch.setattr(ar, "verify_password", lambda pw, h: False)
    yield ar, pooled
    ar.reset_throttles()


def test_login_verifies_in_threadpool(client, auth):
    _, pooled = auth
    r = client.post("/auth/login", json={"email": "a@b.co", "password": "x"})
    assert r.status_code == 401
    assert pooled == ["<lambda>"] or pooled == ["verify_password"]


def test_login_throttled_per_email(client, auth):
    codes = [
        client.post("/auth/login", json={"email": "A@b.co", "password": "x"}).status_code
        for _ in range(6)
    ]
    assert codes == [401] * 5 + [429]
    r = client.post("/auth/login", json={"email": "a@b.co", "password": "x"})
    assert r.json()["detail"]["code"] == "too_many_attempts"
    # A different email from the same IP is still allowed (IP cap is 10).
    assert client.post(
        "/auth/login", json={"email": "c@d.co", "password": "x"}
    ).status_code == 401


def test_login_throttled_per_ip(client, auth):
    codes = [
        client.post(
            "/auth/login", json={"email": f"u{i}@b.co", "password": "x"}
        ).status_code
        for i in range(11)
    ]
    assert codes == [401] * 10 + [429]


def test_sliding_window_expires_and_is_bounded():
    from app.auth.throttle import SlidingWindow

    now = [1000.0]
    w = SlidingWindow(limit=2, window_s=300, max_keys=3, clock=lambda: now[0])
    assert w.hit("k") and w.hit("k") and not w.hit("k")
    now[0] += 301
    assert w.hit("k")
    for i in range(10):
        w.hit(f"x{i}")
    assert len(w) <= 3


@pytest.mark.parametrize(
    "hops,xff,expected",
    [
        (0, "6.6.6.6, 1.2.3.4", "10.0.0.1"),
        (1, "6.6.6.6, 1.2.3.4", "1.2.3.4"),
        (2, "6.6.6.6, 1.2.3.4", "6.6.6.6"),
        (2, "1.2.3.4", "10.0.0.1"),
        (3, "6.6.6.6, 1.2.3.4", "10.0.0.1"),
        (1, "", "10.0.0.1"),
        (1, " , ", "10.0.0.1"),
    ],
)
def test_client_ip_trust_proxy_hops(monkeypatch, hops, xff, expected):
    import app.api.auth_routes as ar

    headers = {"x-forwarded-for": xff} if xff else {}
    req = SimpleNamespace(client=SimpleNamespace(host="10.0.0.1"), headers=headers)
    monkeypatch.setattr(ar.settings, "trust_proxy_hops", hops)
    assert ar.client_ip(req) == expected


# --- minors ---------------------------------------------------------------


def test_ask_input_bounds(client):
    _as(SimpleNamespace(id=7, email="u@x", is_admin=False))
    h = {"X-LLM-Provider": "gemini", "X-LLM-Key": "k"}
    r = client.post("/ask", json={"novel_id": 1, "question": "q" * 2001}, headers=h)
    assert r.status_code == 422
    for k in (0, 21):
        r = client.post(
            "/ask", json={"novel_id": 1, "question": "q", "top_k": k}, headers=h
        )
        assert r.status_code == 422


def test_progress_post_unknown_novel_404(client, monkeypatch):
    import app.api.reader as reader

    monkeypatch.setattr(reader, "get_session", _fake_session)
    monkeypatch.setattr(reader, "get_novel", lambda s, nid: None)

    def boom(*a, **k):
        raise AssertionError("must not write progress")

    monkeypatch.setattr(reader, "set_progress", boom)
    _as(SimpleNamespace(id=7, email="u@x", is_admin=False))
    r = client.post("/progress", json={"novel_id": 99, "current_chapter": 1})
    assert r.status_code == 404


def test_chapter_get_unknown_novel_404(client, monkeypatch):
    import app.api.novels as novels

    monkeypatch.setattr(novels, "get_session", _fake_session)
    monkeypatch.setattr(novels, "get_novel", lambda s, nid: None)
    monkeypatch.setattr(novels, "get_chapter_by_idx", lambda s, n, i: None)

    def boom(*a, **k):
        raise AssertionError("must not write progress")

    monkeypatch.setattr(novels, "advance_progress", boom)
    _as(SimpleNamespace(id=7, email="u@x", is_admin=False))
    assert client.get("/novels/99/chapters/0").status_code == 404


def test_upload_parses_off_the_event_loop(client, monkeypatch):
    import asyncio

    import app.api.novels as novels
    from app.api.schemas import IngestResult

    ran = []
    real = asyncio.to_thread

    async def spy(fn, *a, **k):
        ran.append(getattr(fn, "__name__", repr(fn)))
        return await real(fn, *a, **k)

    monkeypatch.setattr(asyncio, "to_thread", spy)
    monkeypatch.setattr(novels, "load_txt", lambda p: "第一章\n\n你好")
    monkeypatch.setattr(
        novels, "_persist_novel",
        lambda **k: IngestResult(novel_id=1, chapters_added=1, title=k["title"]),
    )
    _as(SimpleNamespace(id=7, email="u@x", is_admin=False))
    r = client.post(
        "/novels/upload", files={"file": ("book.txt", b"hello", "text/plain")}
    )
    assert r.status_code == 200, r.text
    assert ran == ["<lambda>"]
