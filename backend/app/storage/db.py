from contextlib import contextmanager
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..common.config import settings


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres", "host.docker.internal"}


def normalize_db_url(url: str) -> str:
    """Make a plain Postgres URL usable by this stack.

    Two things bite on every hosted Postgres (Supabase, Neon, Render):
      1. SQLAlchemy maps bare ``postgresql://`` to psycopg2, which we do not
         install. Pin the psycopg v3 dialect instead.
      2. Managed providers require TLS. Add ``sslmode=require`` for any
         non-local host that has not already asked for something else.
    """
    if not url:
        return url
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+psycopg"

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    host = (parts.hostname or "").lower()
    if host and host not in _LOCAL_HOSTS and "sslmode" not in query:
        query["sslmode"] = "require"

    return urlunsplit(
        (scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(
            normalize_db_url(url or settings.database_url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            future=True,
        )
        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        )
    return _engine


@contextmanager
def get_session() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
