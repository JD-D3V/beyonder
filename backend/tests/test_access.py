"""Route access matrix, with auth deps overridden and the repository stubbed."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import current_user, current_user_optional
from app.main import app


class _User:
    def __init__(self, uid=7, admin=False):
        self.id = uid
        self.email = "u@example.com"
        self.is_admin = admin


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


def _stub_sessions(monkeypatch):
    for m in ("novels", "translate", "reader"):
        monkeypatch.setattr(f"app.api.{m}.get_session", _fake_session)


NOVEL = SimpleNamespace(id=1, title="T", source_lang="zh")
KEY = {"X-LLM-Provider": "gemini", "X-LLM-Key": "k"}


def test_anonymous_can_list_novels(client, monkeypatch):
    _stub_sessions(monkeypatch)
    monkeypatch.setattr("app.api.novels.library_rows", lambda s: [])
    r = client.get("/novels")
    assert r.status_code == 200 and r.json() == []


def test_anonymous_cannot_translate_401(client):
    r = client.post("/translate", json={"novel_id": 1, "chapter_idx": 0})
    assert r.status_code == 401


def test_user_without_key_translate_402(client, monkeypatch):
    _stub_sessions(monkeypatch)
    _as(_User())
    r = client.post("/translate", json={"novel_id": 1, "chapter_idx": 0})
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "llm_key_required"


def test_non_admin_delete_403(client):
    _as(_User())
    assert client.delete("/novels/1").status_code == 403
    assert client.patch("/novels/1", json={"title": "x"}).status_code == 403


def test_ingest_requires_login(client):
    r = client.post("/novels/ingest/text", json={"title": "t", "text": "x"})
    assert r.status_code == 401


def test_ask_ignores_client_current_chapter(client, monkeypatch):
    _stub_sessions(monkeypatch)
    _as(_User())
    monkeypatch.setattr("app.api.reader.get_novel", lambda s, nid: NOVEL)
    monkeypatch.setattr("app.api.reader.get_progress", lambda s, uid, nid: 3)
    seen = {}

    async def fake_answer(**kw):
        seen.update(kw)
        return SimpleNamespace(answer="a", hits=[])

    monkeypatch.setattr("app.api.reader.answer_question", fake_answer)
    r = client.post(
        "/ask",
        json={"novel_id": 1, "question": "q", "current_chapter": 99},
        headers=KEY,
    )
    assert r.status_code == 200
    assert seen["current_chapter"] == 3


def test_ask_requires_login(client):
    assert client.post("/ask", json={"novel_id": 1, "question": "q"}).status_code == 401


def test_non_admin_cannot_overwrite_complete_translation(client, monkeypatch):
    _stub_sessions(monkeypatch)
    _as(_User())
    monkeypatch.setattr("app.api.translate.get_novel", lambda s, nid: NOVEL)
    monkeypatch.setattr(
        "app.api.translate.get_chapter_by_idx",
        lambda s, nid, idx: SimpleNamespace(id=5, idx=idx),
    )
    monkeypatch.setattr(
        "app.api.translate.get_translation",
        lambda s, chapter_id, target_lang="en": SimpleNamespace(
            text="done", critic_passes=1, pieces_done=None
        ),
    )

    async def boom(**kw):
        raise AssertionError("must not re-translate")

    monkeypatch.setattr("app.api.translate.run_translation_graph", boom)
    monkeypatch.setattr("app.api.translate.translate_step", boom)
    r = client.post(
        "/translate",
        json={"novel_id": 1, "chapter_idx": 0, "force": True},
        headers=KEY,
    )
    assert r.status_code == 200 and r.json()["translation"] == "done"
    r = client.post(
        "/translate/step", json={"novel_id": 1, "chapter_idx": 0}, headers=KEY
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "already_translated"


def test_admin_force_resets_and_records_translator(client, monkeypatch):
    _stub_sessions(monkeypatch)
    _as(_User(uid=1, admin=True))
    monkeypatch.setattr("app.api.translate.get_novel", lambda s, nid: NOVEL)
    monkeypatch.setattr(
        "app.api.translate.get_chapter_by_idx",
        lambda s, nid, idx: SimpleNamespace(id=5, idx=idx),
    )
    monkeypatch.setattr(
        "app.api.translate.get_translation",
        lambda s, chapter_id, target_lang="en": SimpleNamespace(
            text="done", critic_passes=1, pieces_done=None
        ),
    )
    reset = []
    monkeypatch.setattr(
        "app.api.translate.reset_translation",
        lambda s, chapter_id, target_lang: reset.append(chapter_id),
    )
    seen = {}

    async def fake_step(**kw):
        seen.update(kw)
        return SimpleNamespace(
            chapter_idx=0, pieces_done=1, pieces_total=2, complete=False,
            stalled=False, error=None,
        )

    monkeypatch.setattr("app.api.translate.translate_step", fake_step)
    r = client.post(
        "/translate/step",
        json={"novel_id": 1, "chapter_idx": 0, "force": True},
        headers=KEY,
    )
    assert r.status_code == 200
    assert reset == [5]
    assert seen["translated_by"] == 1


def test_llm_error_maps_to_status(client, monkeypatch):
    from app.llm.client import LLMError

    _stub_sessions(monkeypatch)
    _as(_User())
    monkeypatch.setattr("app.api.translate.get_novel", lambda s, nid: NOVEL)
    monkeypatch.setattr("app.api.translate.get_chapter_by_idx", lambda s, n, i: None)

    for code, status in [
        ("llm_key_invalid", 400),
        ("llm_rate_limited", 429),
        ("llm_upstream", 502),
    ]:
        async def fail(**kw):
            raise LLMError(code, "nope")

        monkeypatch.setattr("app.api.translate.run_translation_graph", fail)
        r = client.post(
            "/translate", json={"novel_id": 1, "chapter_idx": 0}, headers=KEY
        )
        assert r.status_code == status
        assert r.json()["code"] == code and r.json()["detail"] == "nope"


def test_glossary_defaults_to_progress_when_signed_in(client, monkeypatch):
    _stub_sessions(monkeypatch)
    _as(_User())
    monkeypatch.setattr("app.api.reader.get_progress", lambda s, uid, nid: 4)
    seen = {}

    def terms(s, nid, up_to_chapter, target_lang):
        seen["up_to"] = up_to_chapter
        return []

    monkeypatch.setattr("app.api.reader.get_terms_for_chapters", terms)
    assert client.get("/novels/1/glossary").status_code == 200
    assert seen["up_to"] == 4
    client.get("/novels/1/glossary?up_to=9")
    assert seen["up_to"] == 9
