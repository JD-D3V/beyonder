"""Merge "T", "T (2)", "T (3)" ... chapter runs back into one chapter.

    python -m app.scripts.merge_parts [--novel ID] [--dry-run | --reembed-only]

Older imports split long header sections into length-based parts titled
``T``, ``T (2)``, ``T (3)`` (see ``splitter._part_title``). Chapters are now
kept whole, so this folds each such run into its first chapter:

  * source texts are joined with a blank line and ``char_count`` recomputed;
  * later parts are deleted and the remaining chapters re-indexed (0..n-1);
  * per language, if every part has a complete translation they are joined,
    otherwise that language's translation of the merged chapter is dropped;
  * reading progress, review flags, glossary and relation ``first_chapter``
    values are remapped to the new indices (anything inside a run maps to the
    run's first chapter);
  * the novel's Qdrant vectors are rebuilt.

One transaction per novel. ``--dry-run`` prints the plan and changes nothing.
The vector rebuild runs after the commit; if it fails the script says so, goes
on with the other novels and exits non-zero. ``--reembed-only`` rebuilds the
vectors for the given/all novels without merging (the recovery for that case).

Stop the backend (or at least translation) before running: a translation
written while chapters are being re-indexed can land on the wrong chapter.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..common.logging import get_logger
from ..storage.db import get_session
from ..storage.models import (
    Chapter,
    Novel,
    ReadingProgress,
    Relation,
    ReviewFlag,
    Term,
    Translation,
)

log = get_logger(__name__)

_JOIN = "\n\n"


@dataclass
class MergePlan:
    novel_id: int
    # Each run is a list of old chapter idx values, first one is kept.
    runs: list[list[int]]
    # old idx -> new idx, for every old chapter.
    mapping: dict[int, int]
    chapters_before: int
    chapters_after: int
    # (run, language) translations dropped because some part was untranslated.
    dropped_translations: int = 0


def find_runs(titles: list[str | None]) -> list[list[int]]:
    """Positions (into ``titles``) of runs ``T``, ``T (2)``, ``T (3)``, ...

    Only exact ``_part_title`` output qualifies, in strictly consecutive order
    starting at 2. Runs shorter than two chapters are not runs.
    """
    runs: list[list[int]] = []
    i = 0
    while i < len(titles):
        base = titles[i]
        if not base:
            i += 1
            continue
        run = [i]
        n = 2
        while i + len(run) < len(titles) and titles[i + len(run)] == f"{base} ({n})":
            run.append(i + len(run))
            n += 1
        if len(run) > 1:
            runs.append(run)
        i += len(run)
    return runs


def _complete(tr: Translation | None) -> bool:
    return tr is not None and tr.pieces_done is None and bool(tr.text)


def plan_for(novel_id: int, chapters: list[Chapter]) -> MergePlan:
    runs = find_runs([c.title for c in chapters])
    idxs = [c.idx for c in chapters]
    in_run: dict[int, int] = {}  # old idx -> old idx of its run's first chapter
    for run in runs:
        for pos in run:
            in_run[idxs[pos]] = idxs[run[0]]
    mapping: dict[int, int] = {}
    new = 0
    for old in idxs:
        head = in_run.get(old, old)
        if head == old:
            mapping[old] = new
            new += 1
        else:
            mapping[old] = mapping[head]
    return MergePlan(
        novel_id=novel_id,
        runs=[[idxs[p] for p in run] for run in runs],
        mapping=mapping,
        chapters_before=len(chapters),
        chapters_after=new,
    )


def _count_dropped(chapters: list[Chapter], runs: list[list[int]]) -> int:
    by_idx = {c.idx: c for c in chapters}
    n = 0
    for run in runs:
        parts = [by_idx[i] for i in run]
        per = [{t.target_lang: t for t in c.translations} for c in parts]
        for lang in {lang for d in per for lang in d}:
            if not all(_complete(d.get(lang)) for d in per):
                n += 1
    return n


def merge_novel(
    session: Session, novel_id: int, *, dry_run: bool = False
) -> MergePlan:
    """Merge every part run of one novel inside the caller's transaction."""
    chapters = list(
        session.scalars(
            select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.idx)
        )
    )
    plan = plan_for(novel_id, chapters)
    plan.dropped_translations = _count_dropped(chapters, plan.runs)
    if dry_run or not plan.runs:
        return plan

    by_idx = {c.idx: c for c in chapters}
    dropped: set[int] = set()
    lost_runs: list[list[int]] = []
    for run in plan.runs:
        parts = [by_idx[i] for i in run]
        head, rest = parts[0], parts[1:]
        trs = {
            c.id: {t.target_lang: t for t in c.translations} for c in parts
        }
        langs = {lang for per in trs.values() for lang in per}
        head.source_text = _JOIN.join(c.source_text for c in parts)
        head.char_count = len(head.source_text)
        for lang in langs:
            rows = [trs[c.id].get(lang) for c in parts]
            head_tr = trs[head.id].get(lang)
            if all(_complete(r) for r in rows):
                head_tr.text = _JOIN.join(r.text for r in rows)
                head_tr.pieces_done = None
                # The head's translated title stays: it names the whole chapter.
            else:
                if head_tr is not None:
                    session.delete(head_tr)
                lost_runs.append(run)
        for c in rest:
            dropped.add(c.idx)
            session.delete(c)
    # QA flags describe the translation that was dropped; they would point at
    # a text that no longer exists.
    for run in lost_runs:
        session.execute(
            delete(ReviewFlag).where(
                ReviewFlag.novel_id == novel_id, ReviewFlag.chapter_idx.in_(run)
            )
        )
    session.flush()

    # Re-index survivors in ascending order; every new idx is <= the old one,
    # and the slot it moves into is already free, so the unique key never trips.
    for old in sorted(by_idx):
        new = plan.mapping[old]
        c = by_idx[old]
        if old in dropped or c.idx == new:
            continue
        c.idx = new
        session.flush()

    # Remap pointers. Ascending with new <= old, so an update never touches rows
    # an earlier update just wrote.
    for old in sorted(plan.mapping):
        new = plan.mapping[old]
        if new == old:
            continue
        session.execute(
            update(ReadingProgress)
            .where(ReadingProgress.novel_id == novel_id, ReadingProgress.chapter_idx == old)
            .values(chapter_idx=new)
        )
        session.execute(
            update(ReviewFlag)
            .where(ReviewFlag.novel_id == novel_id, ReviewFlag.chapter_idx == old)
            .values(chapter_idx=new)
        )
        session.execute(
            update(Term)
            .where(Term.novel_id == novel_id, Term.first_chapter == old)
            .values(first_chapter=new)
        )
        session.execute(
            update(Relation)
            .where(Relation.novel_id == novel_id, Relation.first_chapter == old)
            .values(first_chapter=new)
        )
    session.flush()
    return plan


async def _rebuild_vectors(novel_id: int) -> int:
    from ..embed.pipeline import embed_chapters
    from ..embed.qdrant import delete_novel_chunks

    delete_novel_chunks(novel_id)
    with get_session() as s:
        chaps = list(
            s.scalars(
                select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.idx)
            )
        )
        return await embed_chapters(novel_id, chaps)


async def _safe_rebuild(nid: int) -> bool:
    try:
        n = await _rebuild_vectors(nid)
    except Exception as e:  # noqa: BLE001 - report and carry on with other novels
        print(
            f"  Vectors for novel {nid} could not be rebuilt: {e}. "
            f'Run `make reembed ARGS="--novel {nid}"`'
        )
        return False
    print(f"  re-embedded {n} chunks")
    return True


async def _run(novel_id: int | None, dry_run: bool, reembed_only: bool = False) -> int:
    """Returns the number of novels whose vector rebuild failed."""
    with get_session() as s:
        q = select(Novel.id).order_by(Novel.id)
        if novel_id is not None:
            q = q.where(Novel.id == novel_id)
        ids = list(s.scalars(q))
    failed = 0
    for nid in ids:
        if reembed_only:
            print(f"novel {nid}: rebuilding vectors")
            if not await _safe_rebuild(nid):
                failed += 1
            continue
        with get_session() as s:
            plan = merge_novel(s, nid, dry_run=dry_run)
        if not plan.runs:
            print(f"novel {nid}: nothing to merge")
            continue
        verb = "would merge" if dry_run else "merged"
        print(
            f"novel {nid}: {verb} {len(plan.runs)} runs; chapters "
            f"{plan.chapters_before} -> {plan.chapters_after}"
        )
        for run in plan.runs:
            print(f"  chapters {run[0]}..{run[-1]} ({len(run)} parts) -> {plan.mapping[run[0]]}")
        word = "will be" if dry_run else "were"
        print(
            f"  {plan.dropped_translations} existing translation(s) {word} dropped "
            "because some part was untranslated"
        )
        if not dry_run and not await _safe_rebuild(nid):
            failed += 1
    return failed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--novel", type=int, default=None)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--reembed-only", action="store_true")
    args = ap.parse_args()
    failed = asyncio.run(_run(args.novel, args.dry_run, args.reembed_only))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
