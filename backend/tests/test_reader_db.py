import pytest

from app.storage.models import Novel, User
from app.storage.repository import advance_progress, get_progress, set_progress

pytestmark = pytest.mark.db


def _seed(s):
    u = User(email="r@example.com", password_hash="x")
    n = Novel(title="n", source_lang="zh")
    s.add_all([u, n])
    s.flush()
    return u.id, n.id


def test_reading_advances_but_never_rewinds(db_session):
    uid, nid = _seed(db_session)
    assert advance_progress(db_session, uid, nid, 5) == 5
    assert advance_progress(db_session, uid, nid, 2) == 5
    assert get_progress(db_session, uid, nid) == 5
    assert advance_progress(db_session, uid, nid, 8) == 8


def test_set_progress_can_rewind(db_session):
    uid, nid = _seed(db_session)
    set_progress(db_session, uid, nid, 9)
    set_progress(db_session, uid, nid, 1)
    assert get_progress(db_session, uid, nid) == 1
