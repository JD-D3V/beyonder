"""End-to-end smoke test against a running stack.

Requires:
    docker compose up -d postgres qdrant
    alembic upgrade head
    GEMINI_API_KEY in .env

Usage:
    python -m scripts.smoke
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.common.config import settings  # noqa: E402
from app.common.logging import get_logger  # noqa: E402
from app.embed.pipeline import embed_chapters  # noqa: E402
from app.graph.orchestrator import run_translation_graph  # noqa: E402
from app.ingest.splitter import ParsedChapter  # noqa: E402
from app.storage.db import init_engine, get_session  # noqa: E402
from app.storage.repository import (  # noqa: E402
    create_novel,
    get_chapters,
    insert_chapter,
)

log = get_logger("smoke")

# Two short fabricated chapters of CN text — public domain register,
# safe to ship in the repo.
SAMPLE = [
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
]


async def main() -> int:
    if not settings.has_gemini:
        print("GEMINI_API_KEY missing — set it in .env first", file=sys.stderr)
        return 2

    init_engine()
    with get_session() as s:
        novel = create_novel(s, title="Smoke Test Novel", source_lang="zh")
        chaps = []
        for c in SAMPLE:
            chaps.append(
                insert_chapter(
                    s,
                    novel_id=novel.id,
                    idx=c.idx,
                    title=c.title,
                    source_text=c.text,
                )
            )
        novel_id = novel.id
        s.expunge_all()  # detach for safety

    with get_session() as s:
        chaps = list(get_chapters(s, novel_id))

    log.info("smoke.embed_start")
    pts = await embed_chapters(novel_id, chaps)
    log.info("smoke.embed_done", points=pts)

    log.info("smoke.translate_start")
    state = await run_translation_graph(
        novel_id=novel_id,
        novel_title="Smoke Test Novel",
        source_lang="zh",
        target_lang="en",
        chapter_idx=0,
    )
    log.info(
        "smoke.translate_done",
        critic_passes=state.critic_passes,
        new_terms=len(state.new_terms),
        translation_chars=len(state.translation),
    )
    print("\n----- TRANSLATION -----\n")
    print(state.translation)
    print("\n----- TERMS -----")
    for t in state.new_terms:
        print(f"  {t['source_term']} -> {t['target_term']} ({t['kind']})")
    print("\n----- RELATIONS -----")
    for r in state.relations:
        print(f"  {r['src']} --{r['relation']}--> {r['dst']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
