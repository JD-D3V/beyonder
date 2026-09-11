"""Deterministic demo seed.

Ingests a small fabricated CN novel under the title "smoke" so the eval
harness's gold rows can resolve `novel_slug=smoke` consistently across runs.

Usage:
    python -m scripts.seed_demo
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.common.logging import get_logger  # noqa: E402
from app.ingest.splitter import ParsedChapter  # noqa: E402
from app.storage.db import get_session, init_engine  # noqa: E402
from app.storage.repository import (  # noqa: E402
    create_novel,
    insert_chapter,
    list_novels,
)

log = get_logger("seed")

CHAPTERS = [
    ParsedChapter(
        idx=0,
        title="第一章 山门",
        text=(
            "王林站在山门前，望着远处云雾缭绕的青木峰。\n\n"
            "青木宗，乃是这方天地最大的修仙宗门，号称万年传承不绝。\n\n"
            "他握紧手中那枚来自父亲的玉佩，深吸一口气，迈步向前。"
        ),
    ),
    ParsedChapter(
        idx=1,
        title="第二章 拜师",
        text=(
            "山门之内，王林见到了那位传说中的张长老。\n\n"
            "张长老乃是青木宗的炼气长老，曾经亲手培养出三位金丹境弟子。\n\n"
            "王林躬身行礼，正式拜入青木宗门下，开始了修仙之路。"
        ),
    ),
    ParsedChapter(
        idx=2,
        title="第三章 渡劫",
        text=(
            "三十年后，王林立于青木峰之巅，雷云密布。\n\n"
            "金丹境圆满之后的第一次渡劫，他必须以一己之力扛过九道天雷。\n\n"
            "张长老远远望着，神色复杂，欣慰之中带着一丝担忧。"
        ),
    ),
]

DEMO_TITLE = "Smoke Test Novel"


def main() -> int:
    init_engine()
    with get_session() as s:
        existing = [n for n in list_novels(s) if n.title == DEMO_TITLE]
        if existing:
            log.info("seed.skip", reason="already present", id=existing[0].id)
            print(f"Demo novel already present (id={existing[0].id}).")
            return 0
        novel = create_novel(s, title=DEMO_TITLE, source_lang="zh")
        for c in CHAPTERS:
            insert_chapter(
                s,
                novel_id=novel.id,
                idx=c.idx,
                title=c.title,
                source_text=c.text,
            )
        log.info("seed.done", id=novel.id, chapters=len(CHAPTERS))
        print(f"Seeded demo novel id={novel.id} with {len(CHAPTERS)} chapters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
