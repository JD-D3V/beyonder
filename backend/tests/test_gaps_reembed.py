from contextlib import contextmanager
from types import SimpleNamespace

from app.common.config import settings
from app.scripts import reembed


class _Client:
    def __init__(self, exists=True):
        self.exists = exists
        self.deleted = []

    def collection_exists(self, name):
        return self.exists

    def delete_collection(self, name):
        self.deleted.append(name)


class _Store:
    collection = "col"

    def __init__(self, dim, exists=True):
        self.client = _Client(exists)
        self._dim = dim
        self.ensured = None

    def existing_dim(self):
        return self._dim

    def ensure(self, dim):
        self.ensured = dim


class _DB:
    def __init__(self):
        self.calls = 0

    def scalars(self, q):
        self.calls += 1
        # first call: novel ids; later calls: chapters
        data = [1] if self.calls == 1 else ["c"]
        return SimpleNamespace(all=lambda: data)


def _patch(monkeypatch, store):
    embedded = []

    @contextmanager
    def sess():
        yield _DB()

    async def emb(nid, chaps):
        embedded.append(nid)
        return 3

    monkeypatch.setattr(reembed, "get_qdrant", lambda: store)
    monkeypatch.setattr(reembed, "get_session", sess)
    monkeypatch.setattr(reembed, "embed_chapters", emb)
    return embedded


async def test_full_run_recreates_collection(monkeypatch):
    store = _Store(settings.embedding_dim)
    embedded = _patch(monkeypatch, store)
    await reembed._run(None)
    assert store.client.deleted == ["col"]
    assert store.ensured == settings.embedding_dim
    assert embedded == [1]


async def test_novel_run_with_matching_dim_keeps_collection(monkeypatch):
    store = _Store(settings.embedding_dim)
    embedded = _patch(monkeypatch, store)
    await reembed._run(1)
    assert store.client.deleted == []
    assert embedded == [1]


async def test_novel_run_with_mismatched_dim_recreates(monkeypatch):
    store = _Store(settings.embedding_dim + 1)
    _patch(monkeypatch, store)
    await reembed._run(1)
    assert store.client.deleted == ["col"]
    assert store.ensured == settings.embedding_dim


async def test_novel_run_with_missing_collection_deletes_nothing(monkeypatch):
    store = _Store(None, exists=False)
    _patch(monkeypatch, store)
    await reembed._run(1)
    assert store.client.deleted == []
    assert store.ensured == settings.embedding_dim
