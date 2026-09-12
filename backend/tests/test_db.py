import app.storage.db as db
from app.storage.db import normalize_db_url


def test_normalize_pins_psycopg3_driver():
    # A bare postgresql:// URL routes to psycopg2, which is not installed.
    out = normalize_db_url("postgresql://u:p@localhost:5433/beyonder")
    assert out.startswith("postgresql+psycopg://")


def test_normalize_requires_tls_off_box():
    out = normalize_db_url("postgresql://u:p@aws-0.pooler.supabase.com:5432/postgres")
    assert "sslmode=require" in out


def test_normalize_leaves_local_and_explicit_choices_alone():
    assert "sslmode" not in normalize_db_url("postgresql://u:p@localhost/db")
    assert "sslmode=disable" in normalize_db_url(
        "postgresql+psycopg://u:p@host/db?sslmode=disable"
    )


def test_sessions_keep_columns_readable_after_close():
    # /novels/embed and orchestrator.node_load both read ORM rows after their
    # `with get_session()` block ends. Expiring on commit makes that a
    # DetachedInstanceError. create_engine does not connect, so no DB needed.
    db._engine = None
    db._SessionLocal = None
    db.init_engine("postgresql+psycopg://u:p@localhost:5433/nonexistent")
    try:
        assert db._SessionLocal is not None
        assert db._SessionLocal.kw.get("expire_on_commit") is False
    finally:
        db._engine = None
        db._SessionLocal = None
