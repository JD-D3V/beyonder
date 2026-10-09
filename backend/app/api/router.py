"""Top-level router: health, eval report, and the feature routers."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..common.config import settings
from .library import router as library_router
from .novels import router as novels_router
from .reader import router as reader_router
from .social import router as social_router
from .translate import router as translate_router

router = APIRouter()
router.include_router(novels_router)
router.include_router(translate_router)
router.include_router(reader_router)
router.include_router(library_router)
router.include_router(social_router)



@router.get("/health")
async def health() -> dict:
    """Liveness, plus enough to tell which build and config are actually live.

    Render injects RENDER_GIT_COMMIT, so a stale deploy is visible from here
    instead of guessing at the dashboard. No secrets: model names only.
    """
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    return {
        "ok": True,
        "commit": commit[:7] if commit else "dev",
        "model": settings.gemini_model,
        "embed_model": settings.embed_model_name,
    }



_EVAL_LATEST = Path(__file__).resolve().parents[2] / "eval" / "reports" / "latest.json"


@router.get("/eval/latest")
async def eval_latest() -> dict:
    """Serve the most recent eval run for the dashboard.

    Returns 404 with a hint if no report exists yet.
    """
    if not _EVAL_LATEST.exists():
        raise HTTPException(
            404, "no eval report yet — run: python -m eval.run all"
        )
    try:
        return json.loads(_EVAL_LATEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"corrupt eval report: {e}") from e
