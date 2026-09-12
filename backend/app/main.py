"""FastAPI entry point.

Run:
    uvicorn app.main:app --reload --port 8000

In Docker the same command runs.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import router
from .common.auth import TokenAuthMiddleware
from .common.config import settings
from .common.logging import get_logger
from .storage.db import init_engine

log = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Beyonder",
        version="0.1.0",
        description="Multi-agent Chinese web-novel translation + Q&A",
    )
    # CORS — the frontend is always on another origin, locally (container port
    # mapping) and in production (static host vs API host). Set CORS_ORIGINS.
    # Order matters: this runs before CORS on the way in, and a 401 still needs
    # CORS headers on the way out for the browser to show the body rather than
    # an opaque network error. Starlette applies middleware in reverse order of
    # registration, so registering auth first puts CORS outermost.
    app.add_middleware(TokenAuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.on_event("startup")
    async def _startup() -> None:
        init_engine()
        log.info(
            "startup",
            model=settings.gemini_model,
            cors=settings.cors_origin_list,
            private=settings.is_private,
            embed_model=settings.gemini_embed_model,
            db=settings.database_url.split("@")[-1],
            qdrant=settings.qdrant_url,
        )

    return app


app = create_app()
