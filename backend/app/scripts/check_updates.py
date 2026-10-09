"""Check URL-imported novels for new chapters (run from cron).

    python -m app.scripts.check_updates [--novel ID]
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from ..ingest.updates import UpdateCheckUnavailable, check_novel_updates
from ..storage.db import get_session
from ..storage.models import Novel


async def _run(novel_id: int | None) -> None:
    with get_session() as s:
        q = select(Novel.id).where(Novel.source_index_url.is_not(None))
        if novel_id is not None:
            q = select(Novel.id).where(Novel.id == novel_id)
        ids = list(s.scalars(q).all())
    for nid in ids:
        try:
            print(f"novel {nid}: {await check_novel_updates(nid)} new chapters")
        except UpdateCheckUnavailable as e:
            print(f"novel {nid}: skipped ({e})")
        except Exception as e:  # one bad site must not stop the rest
            print(f"novel {nid}: failed ({e})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--novel", type=int, default=None)
    args = ap.parse_args()
    asyncio.run(_run(args.novel))


if __name__ == "__main__":
    main()
