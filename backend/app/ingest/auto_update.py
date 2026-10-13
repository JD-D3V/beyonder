"""Optional in-process scheduler for new-chapter checks (AUTO_UPDATE_HOURS)."""
from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from ..common.logging import get_logger
from ..storage import db as _db
from ..storage.db import get_session
from ..storage.models import Novel
from .updates import check_novel_updates

log = get_logger(__name__)


async def run_update_pass() -> int:
    """Check every public book that has a source index; returns chapters added."""
    with get_session() as s:
        ids = list(
            s.scalars(
                select(Novel.id).where(
                    Novel.visibility == "public", Novel.source_index_url.is_not(None)
                )
            ).all()
        )
    total = 0
    for nid in ids:
        try:
            total += (await check_novel_updates(nid)).added
        except Exception as e:  # noqa: BLE001 - one bad site must not stop the rest
            log.warning("auto_update.skipped", novel_id=nid, err=str(e))
    return total


LOCK_LEADER = 7003
_leader_conn = None


def try_acquire_leader(key: int = LOCK_LEADER):
    """Take a session-level Postgres advisory lock on a dedicated connection.

    Returns the connection (keep it open to hold the lock) or None when another
    process already holds it.
    """
    if _db._engine is None:
        _db.init_engine()
    conn = _db._engine.connect()
    try:
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k, 0)"), {"k": key}).scalar()
        conn.commit()
    except Exception:
        conn.close()
        raise
    if not got:
        conn.close()
        return None
    return conn


def release_leader(conn, key: int = LOCK_LEADER) -> None:
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:k, 0)"), {"k": key})
        conn.commit()
    finally:
        conn.close()


async def update_loop(hours: float) -> None:
    """Only one process (the advisory-lock holder) runs the update passes."""
    global _leader_conn
    while True:
        await asyncio.sleep(hours * 3600)
        try:
            if _leader_conn is None:
                _leader_conn = await asyncio.to_thread(try_acquire_leader)
            if _leader_conn is None:
                log.info("auto_update.not_leader")
                continue
            added = await run_update_pass()
            log.info("auto_update.pass_done", added=added)
        except Exception as e:  # noqa: BLE001
            log.error("auto_update.pass_failed", err=str(e))
