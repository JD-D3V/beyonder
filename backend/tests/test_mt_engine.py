"""Server-side machine translation: provider, throttle/breaker, job, routes.

All HTTP is mocked; nothing here touches the network.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.common.config import settings
from app.main import app
from app.mt import gate, google_free, job as mt_job
from app.mt.chunking import chunk_text
from app.mt.provider import MTBlocked, MTError


@pytest.fixture(autouse=True)
def _mt_env(monkeypatch):
    monkeypatch.setattr(settings, "mt_provider", "google_free")
    gate.reset()
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(gate, "_sleep", fake_sleep)
    monkeypatch.setattr(gate, "_now", lambda: 1000.0 + 1000.0 * len(slept))
    yield slept
    gate.reset()


def _google(monkeypatch, handler):
    monkeypatch.setattr(google_free, "_transport", httpx.MockTransport(handler))


def _reply(text_by_q):
    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params["q"]
        assert req.url.host == "translate.googleapis.com"
        assert req.url.params["sl"] == "zh-CN" and req.url.params["tl"] == "en"
        out = text_by_q(q)
        return httpx.Response(200, json=[[[out, q, None, None, 10]], None, "zh-CN"])

    return handler


# --- provider ---------------------------------------------------------------

def test_chunking_respects_limit_and_roundtrips():
    para = "你好。" * 100 + "\n"
    text = para * 40
    pieces = chunk_text(text, 1000)
    assert "".join(pieces) == text
    assert all(len(p) <= 1000 for p in pieces) and len(pieces) > 1
    assert chunk_text("短", 1000) == ["短"]
    blob = "字" * 2500  # no punctuation at all: hard cut
    assert "".join(chunk_text(blob, 1000)) == blob


def test_parse_segments_joins_first_column():
    payload = [[["Hello ", "你好"], ["world", "世界"], [None, None]], None, "zh-CN"]
    assert google_free.parse_segments(payload) == "Hello world"
    with pytest.raises(MTError):
        google_free.parse_segments({"x": 1})


async def test_google_free_chunks_and_joins(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req.url.params["q"])
        return httpx.Response(200, json=[[["E" + str(len(seen)) + " ", "x"]], None, "zh-CN"])

    _google(monkeypatch, handler)
    text = ("你好。" * 1000 + "\n") * 2  # ~6000 chars -> 2+ requests
    out = await google_free.GoogleFreeProvider().translate([text, "短"])
    assert len(seen) >= 3 and all(len(q) <= 4500 for q in seen)
    assert out[0].startswith("E1 E2") and out[1].endswith(" ")


async def test_backoff_then_success(monkeypatch, _mt_env):
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429)
        return httpx.Response(200, json=[[["ok", "x"]], None, "zh-CN"])

    monkeypatch.setattr(google_free, "CLIENTS", ("gtx",))
    _google(monkeypatch, handler)
    assert await google_free.GoogleFreeProvider().translate(["你好"]) == ["ok"]
    assert len(calls) == 3
    assert 2.0 in _mt_env and 4.0 in _mt_env  # exponential backoff happened


async def test_breaker_opens_after_three_blocks_then_recovers(monkeypatch, _mt_env):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429)

    monkeypatch.setattr(google_free, "CLIENTS", ("gtx",))
    _google(monkeypatch, handler)
    p = google_free.GoogleFreeProvider()
    for _ in range(3):
        with pytest.raises(MTBlocked):
            await p.translate(["你好"])
    assert len(calls) == 3 * gate.MAX_TRIES
    assert gate.paused()
    before = len(calls)
    with pytest.raises(MTBlocked):  # paused: no request is even sent
        await p.translate(["你好"])
    assert len(calls) == before
    # 15 minutes later the breaker is closed again.
    t = gate._paused_until + 1
    monkeypatch.setattr(gate, "_now", lambda: t)
    assert not gate.paused()


async def test_blocked_client_id_falls_back_to_the_next(monkeypatch):
    clients = []

    def handler(req):
        clients.append(req.url.params["client"])
        if req.url.params["client"] == "gtx":
            return httpx.Response(429, text="<html>Sorry</html>")
        return httpx.Response(200, json=[[["ok", "x"]], None, "zh-CN"])

    _google(monkeypatch, handler)
    assert await google_free.GoogleFreeProvider().translate(["你好"]) == ["ok"]
    assert clients == ["gtx", "dict-chrome-ex"]


async def test_non_retryable_error_is_mterror(monkeypatch):
    _google(monkeypatch, lambda r: httpx.Response(400))
    with pytest.raises(MTError):
        await google_free.GoogleFreeProvider().translate(["你好"])
    _google(monkeypatch, lambda r: httpx.Response(200, text="<html>captcha</html>"))
    with pytest.raises(MTError):
        await google_free.GoogleFreeProvider().translate(["你好"])


async def test_rate_limit_spaces_requests(monkeypatch, _mt_env):
    monkeypatch.setattr(settings, "mt_rps", 1.0)
    monkeypatch.setattr(gate, "_now", lambda: 50.0)  # frozen clock
    _google(monkeypatch, _reply(lambda q: "x"))
    await google_free.GoogleFreeProvider().translate(["a", "b", "c"])
    assert _mt_env == [1.0, 2.0]


def test_glossary_longest_first_and_chapter_gated():
    terms = [("青云", "Qingyun", 0), ("青云宗", "Qingyun Sect", 0),
             ("林动", "Lin Dong", 5), ("宗", "Sect", 0)]
    assert mt_job.apply_glossary("青云宗的林动", terms, 3) == "Qingyun Sect的林动"
    assert mt_job.apply_glossary("青云宗的林动", terms, 5) == "Qingyun Sect的Lin Dong"


# --- job --------------------------------------------------------------------

pytestmark_db = pytest.mark.db


def _book(s, *, chapters=3, visibility="public", owner=None, **kw):
    from app.storage.models import Chapter, Novel

    n = Novel(title="修仙传", author="某人", description="一个故事", source_lang="zh",
              visibility=visibility, owner_id=owner, **kw)
    s.add(n)
    s.flush()
    for i in range(chapters):
        s.add(Chapter(novel_id=n.id, idx=i, title=f"第{i}章", source_text=f"正文{i}" * 5,
                      char_count=10))
    s.commit()
    return n.id


@pytest.mark.db
async def test_job_translates_meta_and_chapters_in_order(db_session, monkeypatch):
    from app.storage.models import Chapter, MtJob, Novel, Term, Translation
    from sqlalchemy import select

    nid = _book(db_session)
    db_session.add(Term(novel_id=nid, source_term="修仙", target_term="Cultivation",
                        first_chapter=0))
    db_session.commit()
    order = []

    def tr(q):
        order.append(q)
        return "EN[" + q + "]"

    _google(monkeypatch, _reply(tr))
    assert mt_job.ensure_job(nid)
    assert not mt_job.ensure_job(nid)  # already active
    await mt_job.run_job(nid)

    db_session.expire_all()
    novel = db_session.get(Novel, nid)
    assert novel.title_en == "EN[修仙传]"
    assert novel.author_en == "EN[某人]" and novel.description_en == "EN[一个故事]"
    rows = db_session.execute(
        select(Chapter.idx, Translation.engine, Translation.title, Translation.text)
        .join(Translation, Translation.chapter_id == Chapter.id).order_by(Chapter.idx)
    ).all()
    assert [r[0] for r in rows] == [0, 1, 2]
    assert all(r[1] == "mt" for r in rows)
    assert rows[0][2] == "EN[第0章]" and rows[0][3].startswith("EN[正文0")
    # chapter 0 is translated before chapter 1
    assert order.index("正文0" * 5) < order.index("正文1" * 5)
    job = db_session.get(MtJob, nid)
    assert (job.status, job.done, job.total) == ("done", 3, 3)
    assert mt_job.status_for(nid) == {"status": "done", "done": 3, "total": 3}

    # Re-running does nothing more (idempotent) and never touches AI rows.
    n_calls = len(order)
    assert mt_job.ensure_job(nid)
    await mt_job.run_job(nid)
    assert len(order) == n_calls


@pytest.mark.db
async def test_job_blocked_marks_failed_and_resumes(db_session, monkeypatch):
    from app.storage.models import MtJob

    nid = _book(db_session, chapters=2)
    state = {"fail": True}

    def handler(req):
        if state["fail"] and req.url.params["q"].startswith("正文1"):
            return httpx.Response(429)
        return httpx.Response(200, json=[[["x", "y"]], None, "zh-CN"])

    _google(monkeypatch, handler)
    mt_job.ensure_job(nid)
    await mt_job.run_job(nid)
    db_session.expire_all()
    job = db_session.get(MtJob, nid)
    assert job.status == "failed" and "paused" in job.error
    assert mt_job.status_for(nid)["done"] == 1

    state["fail"] = False
    gate.reset()
    mt_job.ensure_job(nid)
    await mt_job.run_job(nid)
    assert mt_job.status_for(nid) == {"status": "done", "done": 2, "total": 2}


@pytest.mark.db
async def test_job_ignores_ai_translations_and_english_books(db_session, monkeypatch):
    from app.storage.models import Chapter, Translation
    from sqlalchemy import select

    nid = _book(db_session, chapters=1)
    chap = db_session.scalar(select(Chapter).where(Chapter.novel_id == nid))
    db_session.add(Translation(chapter_id=chap.id, target_lang="en", engine="ai",
                               text="AI text", model="gemini", critic_passes=1))
    db_session.commit()
    _google(monkeypatch, _reply(lambda q: "MT"))
    mt_job.ensure_job(nid)
    await mt_job.run_job(nid)
    db_session.expire_all()
    rows = {t.engine: t.text for t in db_session.scalars(select(Translation))}
    assert rows["ai"] == "AI text" and rows["mt"] == "MT"

    en = _book(db_session, chapters=1)
    from app.storage.models import Novel

    db_session.get(Novel, en).source_lang = "en"
    db_session.commit()
    calls = []
    _google(monkeypatch, lambda r: calls.append(1) or httpx.Response(500))
    mt_job.ensure_job(en)
    await mt_job.run_job(en)
    assert not calls


@pytest.mark.db
def test_sweep_finds_untranslated_books(db_session):
    from app.storage.models import MtJob

    a = _book(db_session)
    b = _book(db_session, visibility="private")
    assert mt_job.find_pending(10) == [a, b]  # private books are translated too
    db_session.add(MtJob(novel_id=a, status="failed", error="x"))
    db_session.commit()
    assert mt_job.find_pending(10) == [b]  # recently failed: not hammered


@pytest.mark.db
def test_enqueue_is_noop_when_off_and_never_raises(db_session, monkeypatch):
    nid = _book(db_session)
    monkeypatch.setattr(settings, "mt_provider", "off")
    assert mt_job.enqueue(nid) is False
    monkeypatch.setattr(settings, "mt_provider", "google_free")
    monkeypatch.setattr(mt_job, "ensure_job", lambda n: 1 / 0)
    assert mt_job.enqueue(nid) is False


# --- engine separation / API shapes ---------------------------------------------

@pytest.mark.db
def test_engines_coexist_and_api_shapes(db_session, monkeypatch):
    from app.auth.deps import current_user_optional
    from app.storage.models import Chapter, Translation
    from sqlalchemy import select

    nid = _book(db_session, chapters=2)
    chaps = db_session.scalars(select(Chapter).where(Chapter.novel_id == nid)
                               .order_by(Chapter.idx)).all()
    db_session.add_all([
        Translation(chapter_id=chaps[0].id, target_lang="en", engine="mt", text="MT0",
                    title="MT title", model="google_free", critic_passes=0),
        Translation(chapter_id=chaps[0].id, target_lang="en", engine="ai", text="AI0",
                    title="AI title", model="gemini", critic_passes=1),
        Translation(chapter_id=chaps[1].id, target_lang="en", engine="mt", text="MT1",
                    title="MT title 1", model="google_free", critic_passes=0),
    ])
    db_session.commit()
    app.dependency_overrides[current_user_optional] = lambda: None
    try:
        with TestClient(app) as c:
            lst = c.get(f"/novels/{nid}/chapters").json()
            assert [(r["translated"], r["mt"], r["title_en"]) for r in lst] == [
                (True, True, "AI title"), (False, True, "MT title 1")]
            d0 = c.get(f"/novels/{nid}/chapters/0").json()
            assert (d0["translation"], d0["translation_mt"], d0["title_en"],
                    d0["title_mt"]) == ("AI0", "MT0", "AI title", "MT title")
            d1 = c.get(f"/novels/{nid}/chapters/1").json()
            assert d1["translation"] is None and d1["translation_mt"] == "MT1"
            n = c.get(f"/novels/{nid}").json()
            assert n["translated_count"] == 2 and n["ai_translated_count"] == 1
            assert n["author_en"] is None and n["description_en"] is None
            st = c.get(f"/novels/{nid}/mt").json()
            assert st == {"status": "done", "done": 2, "total": 2}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.db
def test_upsert_translation_engine_isolated(db_session):
    from app.storage.models import Chapter
    from app.storage.repository import get_translation, upsert_translation
    from sqlalchemy import select

    nid = _book(db_session, chapters=1)
    cid = db_session.scalar(select(Chapter.id).where(Chapter.novel_id == nid))
    assert upsert_translation(db_session, chapter_id=cid, target_lang="en", text="m",
                              model="g", critic_passes=0, engine="mt")
    assert get_translation(db_session, chapter_id=cid) is None  # AI view unchanged
    assert upsert_translation(db_session, chapter_id=cid, target_lang="en", text="a",
                              model="gem", critic_passes=1)
    assert get_translation(db_session, chapter_id=cid).text == "a"
    assert get_translation(db_session, chapter_id=cid, engine="mt").text == "m"


@pytest.mark.db
def test_ingest_text_enqueues_mt(db_session, monkeypatch):
    from types import SimpleNamespace

    from app.auth.deps import current_user
    from app.storage.models import User

    u = User(email="o@x.com", password_hash="x")
    db_session.add(u)
    db_session.commit()
    queued = []
    monkeypatch.setattr(mt_job, "enqueue", lambda nid, **k: queued.append(nid) or True)
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=u.id, email="o@x.com", is_admin=False
    )
    try:
        with TestClient(app) as c:
            r = c.post("/novels/ingest/text", json={
                "title": "T", "text": "第一章\n" + "你好世界。" * 20})
        assert r.status_code == 200, r.text
        assert queued == [r.json()["novel_id"]]  # private import is queued too
    finally:
        app.dependency_overrides.clear()
