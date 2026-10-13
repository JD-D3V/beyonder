"""Local (CPU, ONNX) text embeddings via fastembed. No API key, no cost."""
from __future__ import annotations

import threading
from typing import Sequence

from ..common.config import settings

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                _model = TextEmbedding(model_name=settings.embed_model_name)
    return _model


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Embed texts synchronously. The model loads lazily, once."""
    if not texts:
        return []
    return [vec.tolist() for vec in _get_model().embed(list(texts))]
