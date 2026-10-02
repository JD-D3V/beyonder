from types import SimpleNamespace

import pytest

from app.embed.qdrant import CollectionDimensionError, QdrantStore


class _Client:
    def __init__(self, size):
        self.size = size
        self.recreated = False

    def collection_exists(self, name):
        return self.size is not None

    def get_collection(self, name):
        vec = SimpleNamespace(size=self.size)
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=vec)))

    def recreate_collection(self, **kw):
        self.recreated = True

    def create_payload_index(self, **kw):
        pass


def test_ensure_raises_on_dimension_mismatch():
    store = QdrantStore(_Client(768), "c")
    with pytest.raises(CollectionDimensionError, match="app.scripts.reembed"):
        store.ensure(384)


def test_ensure_ok_when_dim_matches_and_creates_when_missing():
    ok = _Client(384)
    QdrantStore(ok, "c").ensure(384)
    assert not ok.recreated
    missing = _Client(None)
    QdrantStore(missing, "c").ensure(384)
    assert missing.recreated
