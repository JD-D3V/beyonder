"""Ratings, reviews, comments and reports: auth/validation (no DB) and
behaviour against a real Postgres (``db`` marker)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import social
from app.auth.deps import current_user, current_user_optional
from app.main import app


class _U:
    def __init__(self, id, email, is_admin=False):
        self.id, self.email, self.is_admin = id, email, is_admin


@pytest.fixture(autouse=True)
def _fresh_throttles():
    social.reset_throttles()
    yield
    social.reset_throttles()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _as(user):
    app.dependency_overrides[current_user] = lambda: user


# --- no DB ---------------------------------------------------------------

def test_writes_require_sign_in(client):
    assert client.put("/novels/1/review", json={"rating": 3}).status_code == 401
    assert client.delete("/novels/1/review").status_code == 401
    assert client.post(
        "/novels/1/chapters/0/comments", json={"body": "hi"}
    ).status_code == 401
    assert client.delete("/comments/1").status_code == 401
    assert client.post(
        "/reports", json={"kind": "review", "target_id": 1}
    ).status_code == 401


def test_admin_routes_reject_non_admin(client):
    _as(_U(2, "a@x.com"))
    assert client.get("/admin/reports").status_code == 403
    assert client.post("/admin/reports/1/resolve").status_code == 403
    assert client.delete("/reviews/1").status_code == 403


@pytest.mark.parametrize("payload", [
    {"rating": 0}, {"rating": 6}, {"rating": "x"}, {"rating": 3, "body": "x" * 5001},
])
def test_review_validation(client, payload):
    _as(_U(2, "a@x.com"))
    assert client.put("/novels/1/review", json=payload).status_code == 422


@pytest.mark.parametrize("payload", [
    {"body": ""}, {"body": "   "}, {"body": "x" * 2001},
])
def test_comment_validation(client, payload):
    _as(_U(2, "a@x.com"))
    assert client.post(
        "/novels/1/chapters/0/comments", json=payload
    ).status_code == 422


def test_report_validation(client):
    _as(_U(2, "a@x.com"))
    assert client.post(
        "/reports", json={"kind": "novel", "target_id": 1}
    ).status_code == 422
    assert client.post(
        "/reports", json={"kind": "review", "target_id": 1, "reason": "x" * 501}
    ).status_code == 422


def test_display_name_never_leaks_domain():
    assert social._display_name("alice@example.com") == "alice"
    assert social._display_name("") == "reader"


# --- DB ------------------------------------------------------------------

@pytest.fixture
def world(db_session):
    """Novel with 2 chapters plus alice, bob and an admin; committed."""
    import app.storage.db as db
    from app.storage.models import Chapter, Novel, User

    with db.get_session() as s:
        n = Novel(title="T", source_lang="zh")
        s.add(n)
        users = [
            User(email="alice@example.com", password_hash="x"),
            User(email="bob@example.com", password_hash="x"),
            User(email="root@example.com", password_hash="x", is_admin=True),
        ]
        s.add_all(users)
        s.flush()
        for i in range(2):
            s.add(Chapter(novel_id=n.id, idx=i, source_text="x", char_count=1))
        s.flush()
        ids = dict(novel=n.id, alice=users[0].id, bob=users[1].id, root=users[2].id)
    ids["users"] = {
        "alice": _U(ids["alice"], "alice@example.com"),
        "bob": _U(ids["bob"], "bob@example.com"),
        "root": _U(ids["root"], "root@example.com", True),
    }
    return ids


@pytest.mark.db
def test_review_constraints(world):
    import app.storage.db as db
    from app.storage.models import Review

    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(Review(novel_id=world["novel"], user_id=world["alice"], rating=9))
    with db.get_session() as s:
        s.add(Review(novel_id=world["novel"], user_id=world["alice"], rating=4))
    with pytest.raises(IntegrityError):
        with db.get_session() as s:
            s.add(Review(novel_id=world["novel"], user_id=world["alice"], rating=5))


@pytest.mark.db
def test_review_upsert_rating_and_catalog(client, world):
    n = world["novel"]
    _as(world["users"]["alice"])
    r1 = client.put(f"/novels/{n}/review", json={"rating": 4, "body": "good"})
    assert r1.status_code == 200
    r2 = client.put(f"/novels/{n}/review", json={"rating": 2, "body": "  "})
    assert r2.json()["id"] == r1.json()["id"]
    assert r2.json()["rating"] == 2 and r2.json()["body"] is None
    _as(world["users"]["bob"])
    client.put(f"/novels/{n}/review", json={"rating": 5})

    rating = client.get(f"/novels/{n}/rating").json()
    assert rating["count"] == 2 and rating["average"] == 3.5
    assert rating["histogram"] == {"1": 0, "2": 1, "3": 0, "4": 0, "5": 1}

    reviews = client.get(f"/novels/{n}/reviews").json()
    assert [r["author"] for r in reviews] == ["bob", "alice"]  # newest first
    assert "@" not in str(reviews)
    assert len(client.get(f"/novels/{n}/reviews?limit=1&offset=1").json()) == 1

    novel = client.get(f"/novels/{n}").json()
    assert novel["rating_avg"] == 3.5 and novel["rating_count"] == 2
    assert client.get("/novels?sort=rating").json()[0]["id"] == n

    # own delete
    assert client.delete(f"/novels/{n}/review").status_code == 204
    assert client.get(f"/novels/{n}/rating").json()["count"] == 1


@pytest.mark.db
def test_empty_rating_and_missing_novel(client, world):
    n = world["novel"]
    assert client.get(f"/novels/{n}/rating").json() == {
        "average": None, "count": 0,
        "histogram": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
    }
    assert client.get("/novels/9999/rating").status_code == 404
    assert client.get("/novels/9999/reviews").status_code == 404
    assert client.get(f"/novels/{n}").json()["rating_avg"] is None


@pytest.mark.db
def test_admin_deletes_review(client, world):
    n = world["novel"]
    _as(world["users"]["alice"])
    rid = client.put(f"/novels/{n}/review", json={"rating": 1}).json()["id"]
    assert client.delete(f"/reviews/{rid}").status_code == 403
    _as(world["users"]["root"])
    assert client.delete(f"/reviews/{rid}").status_code == 204
    assert client.delete(f"/reviews/{rid}").status_code == 404


@pytest.mark.db
def test_comments_threading_and_soft_delete(client, world):
    n = world["novel"]
    url = f"/novels/{n}/chapters/0/comments"
    _as(world["users"]["alice"])
    a = client.post(url, json={"body": "first"}).json()
    b = client.post(url, json={"body": "second"}).json()
    _as(world["users"]["bob"])
    r1 = client.post(url, json={"body": "r1", "parent_id": a["id"]}).json()
    r2 = client.post(url, json={"body": "r2", "parent_id": a["id"]}).json()

    # replies are one level only; must stay in the same chapter
    assert client.post(
        url, json={"body": "x", "parent_id": r1["id"]}
    ).status_code == 400
    assert client.post(
        f"/novels/{n}/chapters/1/comments", json={"body": "x", "parent_id": a["id"]}
    ).status_code == 400
    assert client.post(url, json={"body": "x", "parent_id": 99999}).status_code == 404

    tree = client.get(url).json()
    assert [c["id"] for c in tree] == [b["id"], a["id"]]  # newest first
    assert [c["id"] for c in tree[1]["replies"]] == [r1["id"], r2["id"]]
    assert tree[1]["author"] == "alice" and "@" not in str(tree)

    # bob cannot delete alice's comment; admin and author can
    assert client.delete(f"/comments/{a['id']}").status_code == 403
    _as(world["users"]["alice"])
    assert client.delete(f"/comments/{a['id']}").status_code == 204
    tree = client.get(url).json()
    deleted = next(c for c in tree if c["id"] == a["id"])
    assert deleted["body"] == "[deleted]" and deleted["author"] is None
    assert len(deleted["replies"]) == 2

    # no replies -> omitted entirely
    _as(world["users"]["root"])
    assert client.delete(f"/comments/{b['id']}").status_code == 204
    assert [c["id"] for c in client.get(url).json()] == [a["id"]]
    # deleted reply vanishes; deleted parent with no replies left disappears
    assert client.delete(f"/comments/{r1['id']}").status_code == 204
    assert client.delete(f"/comments/{r2['id']}").status_code == 204
    assert client.get(url).json() == []
    assert client.delete("/comments/99999").status_code == 404


@pytest.mark.db
def test_comments_404_for_missing_chapter(client, world):
    n = world["novel"]
    assert client.get(f"/novels/{n}/chapters/7/comments").status_code == 404
    assert client.get("/novels/9999/chapters/0/comments").status_code == 404
    _as(world["users"]["alice"])
    assert client.post(
        f"/novels/{n}/chapters/7/comments", json={"body": "hi"}
    ).status_code == 404


@pytest.mark.db
def test_comment_rate_limit(client, world):
    n = world["novel"]
    _as(world["users"]["alice"])
    url = f"/novels/{n}/chapters/0/comments"
    for i in range(10):
        assert client.post(url, json={"body": f"c{i}"}).status_code == 201
    r = client.post(url, json={"body": "one too many"})
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "too_many_posts"
    _as(world["users"]["bob"])  # per-user
    assert client.post(url, json={"body": "ok"}).status_code == 201


@pytest.mark.db
def test_review_rate_limit(client, world):
    n = world["novel"]
    _as(world["users"]["alice"])
    for i in range(5):
        assert client.put(
            f"/novels/{n}/review", json={"rating": 1 + i % 5}
        ).status_code == 200
    r = client.put(f"/novels/{n}/review", json={"rating": 3})
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "too_many_posts"


@pytest.mark.db
def test_reports_idempotent_and_admin_flow(client, world):
    n = world["novel"]
    _as(world["users"]["alice"])
    cid = client.post(
        f"/novels/{n}/chapters/0/comments", json={"body": "spam"}
    ).json()["id"]
    _as(world["users"]["bob"])
    body = {"kind": "comment", "target_id": cid, "reason": "spammy"}
    assert client.post("/reports", json=body).status_code == 200
    assert client.post("/reports", json=body).status_code == 200  # idempotent
    assert client.post(
        "/reports", json={"kind": "review", "target_id": 99999}
    ).status_code == 404

    _as(world["users"]["root"])
    pending = client.get("/admin/reports?resolved=false").json()
    assert len(pending) == 1
    rep = pending[0]
    assert rep["target_body"] == "spam" and rep["target_author"] == "alice"
    assert rep["reporter"] == "bob"
    assert client.post(f"/admin/reports/{rep['id']}/resolve").status_code == 200
    assert client.get("/admin/reports").json() == []
    assert len(client.get("/admin/reports?resolved=true").json()) == 1
    assert client.post("/admin/reports/99999/resolve").status_code == 404


@pytest.mark.db
def test_cascade_on_user_delete(world, db_session):
    import app.storage.db as db
    from app.storage.models import Comment, Review, User

    with db.get_session() as s:
        s.add(Review(novel_id=world["novel"], user_id=world["alice"], rating=3))
        s.add(Comment(
            novel_id=world["novel"], chapter_idx=0, user_id=world["alice"], body="x"
        ))
    with db.get_session() as s:
        s.delete(s.get(User, world["alice"]))
    with db.get_session() as s:
        assert s.execute(select(Review)).first() is None
        assert s.execute(select(Comment)).first() is None
