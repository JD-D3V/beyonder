import math

import pytest

from app.embed import local, pipeline


async def test_pipeline_uses_local_embedder(monkeypatch):
    monkeypatch.setattr(local, "embed_texts", lambda texts: [[0.0] * 384 for _ in texts])
    vec = await pipeline.embed_query("q")
    assert len(vec) == 384
    assert not hasattr(pipeline, "get_gemini")


@pytest.mark.slow
def test_embed_texts_real_model():
    a, b = local.embed_texts(
        ["The hero draws his sword.", "The hero draws his sword!"]
    )
    assert len(a) == 384
    dot = sum(x * y for x, y in zip(a, b))
    cos = dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
    assert cos > 0.8
