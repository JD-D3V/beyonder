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
    en, zh, other = local.embed_texts(
        [
            "The hero draws his sword and charges at the dragon.",
            "英雄拔出剑，向巨龙冲去。",
            "The bakery sells fresh bread every morning.",
        ]
    )
    assert len(en) == 384

    def cos(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

    assert cos(en, zh) > cos(en, other)
