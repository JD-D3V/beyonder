import pytest

from app.storage.models import Chapter, Novel
from app.storage.repository import upsert_translation

pytestmark = pytest.mark.db


def _chapter(s):
    n = Novel(title="n", source_lang="zh")
    s.add(n)
    s.flush()
    c = Chapter(novel_id=n.id, idx=0, title="c", source_text="x", char_count=1)
    s.add(c)
    s.flush()
    return c.id


def _w(s, cid, text, pd=None, **kw):
    return upsert_translation(
        s, chapter_id=cid, target_lang="en", text=text, model="m",
        critic_passes=0, pieces_done=pd, **kw,
    )


def test_complete_row_not_clobbered_without_overwrite(db_session):
    cid = _chapter(db_session)
    assert _w(db_session, cid, "final") is True
    assert _w(db_session, cid, "other") is False
    assert _w(db_session, cid, "partial", pd=1) is False
    assert _w(db_session, cid, "forced", overwrite=True) is True


def test_partial_row_can_be_continued(db_session):
    cid = _chapter(db_session)
    assert _w(db_session, cid, "p1", pd=1) is True
    assert _w(db_session, cid, "p1p2", pd=2) is True
    assert _w(db_session, cid, "done") is True
