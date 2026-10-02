"""FastAPI entry point.

Run:
    uvicorn app.main:app --reload --port 8000

In Docker the same command runs.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .api.auth_routes import router as auth_router
from .api.router import router
from .common.config import settings
from .common.logging import get_logger
from .llm.client import LLMError
from .storage.db import init_engine

log = get_logger(__name__)

_LLM_STATUS = {"llm_key_invalid": 400, "llm_rate_limited": 429, "llm_upstream": 502}


async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(
        status_code=_LLM_STATUS.get(exc.code, 502),
        content={"detail": {"code": exc.code, "detail": str(exc)}},
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Beyonder",
        version="0.1.0",
        description="Multi-agent Chinese web-novel translation + Q&A",
    )
    # CORS — the frontend is always on another origin, locally (container port
    # mapping) and in production (static host vs API host). Set CORS_ORIGINS.
    # The frontend is always on another origin (container port mapping locally,
    # static host vs API host in production). Set CORS_ORIGINS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_exception_handler(LLMError, llm_error_handler)
    app.include_router(router)
    app.include_router(auth_router)

    @app.on_event("startup")
    async def _startup() -> None:
        init_engine()
        log.info(
            "startup",
            model=settings.gemini_model,
            cors=settings.cors_origin_list,
            embed_model=settings.embed_model_name,
            db=settings.database_url.split("@")[-1],
            qdrant=settings.qdrant_url,
        )

    return app


app = create_app()
