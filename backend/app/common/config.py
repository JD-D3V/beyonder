from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "text-embedding-004"
    gemini_rpm_limit: int = 15
    gemini_concurrency: int = 3

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "beyonder_chunks"

    # Postgres
    database_url: str = "postgresql://beyonder:beyonder@localhost:5433/beyonder"

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    log_level: str = "INFO"

    # Comma-separated list of browser origins allowed to call this API.
    # "*" allows any origin (fine here: the API carries no cookies or auth).
    cors_origins: str = "http://localhost:3000"

    # URL ingestion: "auto" uses a headless browser when one is installed and
    # falls back to a plain HTTP fetch; "http" never launches a browser, which
    # is what small cloud instances want.
    scraper_backend: str = "auto"

    # Spoiler default
    default_current_chapter: int = 0

    # Embedding config
    embedding_dim: int = 768  # text-embedding-004
    chunk_target_tokens: int = 500
    chunk_overlap_tokens: int = 50

    # Translator retry
    critic_max_retries: int = 2

    # Eval
    eval_target_qa_accuracy: float = 0.85
    eval_target_term_consistency: float = 0.85
    eval_target_spoiler_leakage: float = 0.0

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    return Settings()


settings = _get_settings()
