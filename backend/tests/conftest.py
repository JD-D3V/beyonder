import os

import pytest


@pytest.fixture
def db_session():
    """A session on a throwaway Postgres schema; skips unless TEST_DATABASE_URL.

    Tables are created fresh and dropped afterwards, so point this at a
    scratch database, never at real data.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")

    import app.storage.db as db
    from app.storage.models import Base
    from sqlalchemy import text

    db._engine = None
    db._SessionLocal = None
    engine = db.init_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with db.get_session() as s:
        yield s
    Base.metadata.drop_all(engine)
    db._engine = None
    db._SessionLocal = None
