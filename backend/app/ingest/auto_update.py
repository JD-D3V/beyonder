"""Optional in-process scheduler for new-chapter checks (AUTO_UPDATE_HOURS)."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from ..common.logging import get_logger
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


async def update_loop(hours: float) -> None:
    while True:
        await asyncio.sleep(hours * 3600)
        try:
            added = await run_update_pass()
            log.info("auto_update.pass_done", added=added)
        except Exception as e:  # noqa: BLE001
            log.error("auto_update.pass_failed", err=str(e))
