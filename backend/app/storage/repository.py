"""Thin data-access helpers. Keep agents/API code free of raw SQL.

Functions here take an open Session — they never open or commit their own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Sequence

from sqlalchemy import Select, delete as sa_delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..common.config import settings
from .models import (
    Chapter, LibraryEntry, Novel, NovelDailyStat, Review, ReadingProgress, Relation, ReviewFlag, Term, Translation,
)


# --- Novels ---------------------------------------------------------------

def create_novel(
    session: Session, *, title: str, source_lang: str, source_url: str | None = None
) -> Novel:
    novel = Novel(title=title, source_lang=source_lang, source_url=source_url)
    session.add(novel)
    session.flush()
    return novel


def get_novel(session: Session, novel_id: int) -> Novel | None:
    return session.get(Novel, novel_id)


def list_novels(session: Session) -> Sequence[Novel]:
    return session.execute(select(Novel).order_by(Novel.id)).scalars().all()


# --- Chapters -------------------------------------------------------------

def insert_chapter(
    session: Session,
    *,
    novel_id: int,
    idx: int,
    title: str | None,
    source_text: str,
) -> Chapter:
    chap = Chapter(
        novel_id=novel_id,
        idx=idx,
        title=title,
        source_text=source_text,
        char_count=len(source_text),
    )
    session.add(chap)
    session.flush()
    return chap


def get_chapters(
    session: Session, novel_id: int, *, up_to: int | None = None
) -> Sequence[Chapter]:
    stmt = select(Chapter).where(Chapter.novel_id == novel_id)
    if up_to is not None:
        stmt = stmt.where(Chapter.idx <= up_to)
    return session.execute(stmt.order_by(Chapter.idx)).scalars().all()


def get_chapter_by_idx(session: Session, novel_id: int, idx: int) -> Chapter | None:
    return session.execute(
        select(Chapter).where(Chapter.novel_id == novel_id, Chapter.idx == idx)
    ).scalar_one_or_none()


# --- Translations ---------------------------------------------------------

def upsert_translation(
    session: Session,
    *,
    chapter_id: int,
    target_lang: str,
    text: str,
    model: str,
    critic_passes: int,
    pieces_done: int | None = None,
    translated_by: int | None = None,
    overwrite: bool = False,
    allow_empty: bool = False,
    title: str | None = None,
) -> bool:
    """Insert or replace the translation for (chapter, lang). True if it wrote.

    ``pieces_done`` is the resumable-progress marker: leave it None to mark the
    row complete (single-pass results and finished step runs), or pass the count
    of pieces done so far to store a partial the next step call resumes from.

    Unless ``overwrite`` is set, a row that is already complete (``pieces_done``
    is NULL and text non-empty) is never replaced: two requests racing on one
    chapter, or a stale partial, cannot clobber a finished translation. The
    existing row is locked (FOR UPDATE) while deciding, and a concurrent first
    insert is caught by the unique constraint, so the check and write are atomic.

    A blank text is never stored as complete (``pieces_done`` None): that would
    publish an empty chapter that non-admins can never replace. Only a chapter
    whose source is itself empty may pass ``allow_empty=True``. Raises
    ValueError otherwise.
    """
    if pieces_done is None and not text.strip() and not allow_empty:
        raise ValueError("refusing to store a blank translation as complete")
    existing = session.execute(
        select(Translation)
        .where(
            Translation.chapter_id == chapter_id,
            Translation.target_lang == target_lang,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        if (
            not overwrite
            and existing.pieces_done is None
            and bool(existing.text)
        ):
            return False
        existing.text = text
        existing.model = model
        existing.critic_passes = critic_passes
        existing.pieces_done = pieces_done
        if title is not None:
            existing.title = title
        if translated_by is not None:
            existing.translated_by = translated_by
        session.flush()
        return True
    try:
        with session.begin_nested():
            session.add(
                Translation(
                    chapter_id=chapter_id,
                    target_lang=target_lang,
                    text=text,
                    model=model,
                    critic_passes=critic_passes,
                    pieces_done=pieces_done,
                    translated_by=translated_by,
                    title=title,
                )
            )
    except IntegrityError:
        # Someone inserted first. Retry once against their row (a partial of
        # theirs may still be replaced by us; a complete one will not be).
        return upsert_translation(
            session, chapter_id=chapter_id, target_lang=target_lang, text=text,
            model=model, critic_passes=critic_passes, pieces_done=pieces_done,
            translated_by=translated_by, overwrite=overwrite,
            allow_empty=allow_empty, title=title,
        )
    return True


def reset_translation(session: Session, *, chapter_id: int, target_lang: str) -> None:
    """Delete the saved translation so a forced re-translate starts clean."""
    session.execute(
        sa_delete(Translation).where(
            Translation.chapter_id == chapter_id,
            Translation.target_lang == target_lang,
        )
    )
    session.flush()


# --- Terms ----------------------------------------------------------------

def _select_term(session: Session, novel_id: int, src: str, target_lang: str):
    return session.execute(
        select(Term).where(
            Term.novel_id == novel_id,
            Term.source_term == src,
            Term.target_lang == target_lang,
        )
    ).scalar_one_or_none()


def upsert_terms(
    session: Session,
    *,
    novel_id: int,
    entries: Iterable[dict],
    target_lang: str = "en",
    created_out: list[Term] | None = None,
) -> list[Term]:
    """Insert or update terms. Higher-confidence wins; locked rows never change.

    Rows created by this call are also appended to ``created_out`` if given.
    Each insert runs in a savepoint: if a concurrent request inserted the same
    term first (unique ``uq_term_novel_src_lang``), the savepoint is rolled
    back and the term is merged into their row instead of failing with a 500
    after the model call has already been paid for.
    """
    out: list[Term] = []
    for e in entries:
        src = e["source_term"].strip()
        tgt = e["target_term"].strip()
        if not src or not tgt:
            continue
        kind = e.get("kind", "other")
        first_chapter = int(e.get("first_chapter", 0))
        conf = float(e.get("confidence", 0.5))
        notes = e.get("notes")
        embedding = e.get("embedding")
        added_by = e.get("added_by")

        existing = _select_term(session, novel_id, src, target_lang)
        if existing is None:
            t = Term(
                novel_id=novel_id,
                source_term=src,
                target_term=tgt,
                target_lang=target_lang,
                kind=kind,
                first_chapter=first_chapter,
                confidence=conf,
                notes=notes,
                embedding=embedding,
                added_by=added_by,
            )
            try:
                with session.begin_nested():
                    session.add(t)
            except IntegrityError:
                existing = _select_term(session, novel_id, src, target_lang)
                if existing is None:  # pragma: no cover - deleted meanwhile
                    raise
            else:
                out.append(t)
                if created_out is not None:
                    created_out.append(t)
                continue
        if existing.locked:
            # Admin-curated: leave the rendering alone.
            out.append(existing)
        else:
            if conf > existing.confidence:
                existing.target_term = tgt
                existing.confidence = conf
                existing.kind = kind
                existing.notes = notes or existing.notes
                if embedding is not None:
                    existing.embedding = embedding
            existing.first_chapter = min(existing.first_chapter, first_chapter)
            out.append(existing)
    session.flush()
    return out


def insert_seed_terms(
    session: Session,
    *,
    novel_id: int,
    entries: Iterable[dict],
    target_lang: str = "en",
) -> list[Term]:
    """Insert seed terms whose source is missing. Returns only rows created.

    ``INSERT ... ON CONFLICT DO NOTHING`` so two requests seeding the same
    chapter cannot collide. A row that already exists keeps its rendering,
    confidence and lock; only its ``first_chapter`` is lowered when this seed
    hit is earlier, so the term is visible from the first chapter it occurs in.
    """
    out: list[Term] = []
    seen: set[str] = set()
    for e in entries:
        src = e["source_term"].strip()
        tgt = e["target_term"].strip()
        if not src or not tgt or src in seen:
            continue
        seen.add(src)
        first_chapter = int(e.get("first_chapter", 0))
        stmt = (
            pg_insert(Term)
            .values(
                novel_id=novel_id,
                source_term=src,
                target_term=tgt,
                target_lang=target_lang,
                kind=e.get("kind", "other"),
                first_chapter=first_chapter,
                confidence=float(e.get("confidence", 0.9)),
                notes=e.get("notes"),
                added_by=e.get("added_by"),
                locked=False,
            )
            .on_conflict_do_nothing(constraint="uq_term_novel_src_lang")
            .returning(Term)
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row is not None:
            out.append(row)
            continue
        session.execute(
            update(Term)
            .where(
                Term.novel_id == novel_id,
                Term.source_term == src,
                Term.target_lang == target_lang,
                Term.first_chapter > first_chapter,
            )
            .values(first_chapter=first_chapter)
            .execution_options(synchronize_session=False)
        )
    session.flush()
    return out


def term_dicts(terms: Iterable[Term]) -> list[dict]:
    """Persisted terms as API-shaped dicts (with ids), de-duplicated."""
    seen: set[int] = set()
    out: list[dict] = []
    for t in terms:
        if t.id in seen:
            continue
        seen.add(t.id)
        out.append(
            {
                "id": t.id,
                "locked": bool(t.locked),
                "source_term": t.source_term,
                "target_term": t.target_term,
                "kind": t.kind,
                "first_chapter": t.first_chapter,
                "confidence": t.confidence,
            }
        )
    return out


def get_terms_for_chapters(
    session: Session, novel_id: int, *, up_to_chapter: int, target_lang: str = "en"
) -> Sequence[Term]:
    return session.execute(
        select(Term)
        .where(
            Term.novel_id == novel_id,
            Term.target_lang == target_lang,
            Term.first_chapter <= up_to_chapter,
        )
        .order_by(Term.confidence.desc())
    ).scalars().all()


def find_terms_in_text(
    session: Session, novel_id: int, text: str, *, target_lang: str = "en"
) -> list[Term]:
    """Substring match — cheap first pass. Embedding search lives in embed/."""
    terms = session.execute(
        select(Term).where(
            Term.novel_id == novel_id, Term.target_lang == target_lang
        )
    ).scalars().all()
    return [t for t in terms if t.source_term and t.source_term in text]


# --- Relations ------------------------------------------------------------

def insert_relations(
    session: Session, *, novel_id: int, entries: Iterable[dict]
) -> list[Relation]:
    out = []
    for e in entries:
        r = Relation(
            novel_id=novel_id,
            src_term=e["src"].strip(),
            relation=e["relation"].strip(),
            dst_term=e["dst"].strip(),
            first_chapter=int(e.get("first_chapter", 0)),
            confidence=float(e.get("confidence", 0.5)),
        )
        session.add(r)
        out.append(r)
    session.flush()
    return out


def get_relations(
    session: Session, novel_id: int, *, up_to_chapter: int
) -> Sequence[Relation]:
    return session.execute(
        select(Relation).where(
            Relation.novel_id == novel_id,
            Relation.first_chapter <= up_to_chapter,
        )
    ).scalars().all()


# --- Reading progress -------------------------------------------------------

def get_progress(session: Session, user_id: int, novel_id: int) -> int:
    row = session.get(ReadingProgress, (user_id, novel_id))
    return row.chapter_idx if row else settings.default_current_chapter


def set_progress(session: Session, user_id: int, novel_id: int, idx: int) -> None:
    row = session.get(ReadingProgress, (user_id, novel_id))
    if row is None:
        session.add(
            ReadingProgress(user_id=user_id, novel_id=novel_id, chapter_idx=int(idx))
        )
    else:
        row.chapter_idx = int(idx)
    session.flush()


def advance_progress(session: Session, user_id: int, novel_id: int, idx: int) -> int:
    """Move the reading position forward only; returns the resulting position."""
    row = session.get(ReadingProgress, (user_id, novel_id))
    if row is None:
        session.add(
            ReadingProgress(user_id=user_id, novel_id=novel_id, chapter_idx=int(idx))
        )
        session.flush()
        return int(idx)
    if int(idx) > row.chapter_idx:
        row.chapter_idx = int(idx)
        session.flush()
    return row.chapter_idx


# --- Library views --------------------------------------------------------

@dataclass(frozen=True)
class LibraryRow:
    """A novel plus the counts the shelf shows, gathered in one query."""

    novel: Novel
    chapter_count: int
    char_count: int
    translated_count: int
    views_total: int = 0
    rating_avg: float | None = None
    rating_count: int = 0


@dataclass(frozen=True)
class CatalogParams:
    """Filters, sort and paging for the catalog; defaults mean 'everything'."""

    q: str | None = None
    tag: str | None = None
    status: str | None = None
    min_chapters: int | None = None
    max_chapters: int | None = None
    sort: str = "updated"  # updated | new | chapters | views | rating
    limit: int | None = None
    offset: int = 0
    ids: tuple[int, ...] | None = None  # restrict to these novels


def _like_escape(raw: str) -> str:
    return (
        raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def catalog_query(params: CatalogParams) -> Select:
    """The catalog SELECT: (Novel, chapters, chars, translated), filtered.

    Pure (no session) so the SQL can be asserted on directly.
    """
    chap = (
        select(
            Chapter.novel_id.label("novel_id"),
            func.count(Chapter.id).label("chapters"),
            func.coalesce(func.sum(Chapter.char_count), 0).label("chars"),
        )
        .group_by(Chapter.novel_id)
        .subquery()
    )
    trans = (
        select(
            Chapter.novel_id.label("novel_id"),
            func.count(func.distinct(Translation.chapter_id)).label("translated"),
        )
        .join(Translation, Translation.chapter_id == Chapter.id)
        # Only fully-translated chapters count; a resumable partial has a row
        # with pieces_done set and is not done yet.
        .where(Translation.pieces_done.is_(None))
        .group_by(Chapter.novel_id)
        .subquery()
    )
    views = (
        select(
            NovelDailyStat.novel_id.label("novel_id"),
            func.sum(NovelDailyStat.views).label("views"),
        )
        .group_by(NovelDailyStat.novel_id)
        .subquery()
    )
    rate = (
        select(
            Review.novel_id.label("novel_id"),
            func.avg(Review.rating).label("avg"),
            func.count(Review.id).label("n"),
        )
        .group_by(Review.novel_id)
        .subquery()
    )
    n_chapters = func.coalesce(chap.c.chapters, 0)
    n_views = func.coalesce(views.c.views, 0)
    stmt = (
        select(
            Novel,
            n_chapters,
            func.coalesce(chap.c.chars, 0),
            func.coalesce(trans.c.translated, 0),
            n_views,
            rate.c.avg,
            func.coalesce(rate.c.n, 0),
        )
        .outerjoin(chap, chap.c.novel_id == Novel.id)
        .outerjoin(trans, trans.c.novel_id == Novel.id)
        .outerjoin(views, views.c.novel_id == Novel.id)
        .outerjoin(rate, rate.c.novel_id == Novel.id)
    )
    if params.q and params.q.strip():
        pat = f"%{_like_escape(params.q.strip())}%"
        stmt = stmt.where(
            Novel.title.ilike(pat, escape="\\")
            | Novel.author.ilike(pat, escape="\\")
        )
    if params.tag and params.tag.strip():
        # Stored as "a, b c" (lowercased); normalise to ",a,b c," and match a
        # whole tag so "art" never matches "martial arts".
        tag = _like_escape(params.tag.strip().lower())
        joined = "," + func.replace(func.coalesce(Novel.tags, ""), ", ", ",") + ","
        stmt = stmt.where(joined.like(f"%,{tag},%", escape="\\"))
    if params.ids is not None:
        stmt = stmt.where(Novel.id.in_(params.ids))
    if params.status:
        stmt = stmt.where(Novel.status == params.status)
    if params.min_chapters is not None:
        stmt = stmt.where(n_chapters >= params.min_chapters)
    if params.max_chapters is not None:
        stmt = stmt.where(n_chapters <= params.max_chapters)
    if params.sort == "new":
        primary = Novel.created_at.desc()
    elif params.sort == "chapters":
        primary = n_chapters.desc()
    elif params.sort == "views":
        primary = n_views.desc()
    elif params.sort == "rating":
        primary = rate.c.avg.desc().nulls_last()
    else:
        primary = Novel.updated_at.desc()
    stmt = stmt.order_by(primary, Novel.id.desc())
    if params.limit is not None:
        stmt = stmt.limit(params.limit).offset(params.offset)
    return stmt


def library_rows(
    session: Session, params: CatalogParams | None = None
) -> list[LibraryRow]:
    """Novels with their chapter, character and translated-chapter counts.

    Aggregated in SQL: a shelf of 200 books should still be one round trip.
    """
    stmt = catalog_query(params or CatalogParams())
    return [
        LibraryRow(
            novel=n, chapter_count=c, char_count=ch, translated_count=t,
            views_total=int(v),
            rating_avg=float(ra) if ra is not None else None,
            rating_count=int(rc),
        )
        for n, c, ch, t, v, ra, rc in session.execute(stmt).all()
    ]


# --- Per-user shelves -----------------------------------------------------

def set_shelf(session: Session, user_id: int, novel_id: int, shelf: str) -> None:
    """Upsert in one statement so two concurrent PUTs cannot collide."""
    session.execute(
        pg_insert(LibraryEntry)
        .values(user_id=user_id, novel_id=novel_id, shelf=shelf)
        .on_conflict_do_update(
            index_elements=[LibraryEntry.user_id, LibraryEntry.novel_id],
            set_={"shelf": shelf, "updated_at": func.now()},
        )
    )
    session.flush()


def remove_shelf(session: Session, user_id: int, novel_id: int) -> None:
    """Idempotent: removing a book that is not shelved is a no-op."""
    session.execute(
        sa_delete(LibraryEntry).where(
            LibraryEntry.user_id == user_id, LibraryEntry.novel_id == novel_id
        )
    )


def shelf_rows(
    session: Session, user_id: int
) -> list[tuple[str, LibraryRow, int]]:
    """(shelf, row, current_chapter) for one user's shelved books, newest first."""
    entries = session.execute(
        select(LibraryEntry.novel_id, LibraryEntry.shelf)
        .where(LibraryEntry.user_id == user_id)
        .order_by(LibraryEntry.updated_at.desc(), LibraryEntry.novel_id.desc())
    ).all()
    if not entries:
        return []
    ids = [nid for nid, _ in entries]
    by_id = {
        r.novel.id: r
        for r in library_rows(session, CatalogParams(ids=tuple(ids)))
    }
    progress = dict(
        session.execute(
            select(ReadingProgress.novel_id, ReadingProgress.chapter_idx).where(
                ReadingProgress.user_id == user_id,
                ReadingProgress.novel_id.in_(ids),
            )
        ).all()
    )
    return [
        (shelf, by_id[nid], progress.get(nid, 0))
        for nid, shelf in entries
        if nid in by_id
    ]


@dataclass(frozen=True)
class ChapterRow:
    idx: int
    title: str | None
    char_count: int
    translated: bool  # complete only
    # Set when a resumable translation is mid-flight (pieces done so far); None
    # when the chapter is untranslated or fully complete.
    pieces_done: int | None = None
    title_en: str | None = None


def chapter_rows(
    session: Session, novel_id: int, *, target_lang: str = "en"
) -> list[ChapterRow]:
    """Chapter list for a book page, each flagged translated / partial / none."""
    stmt = (
        select(
            Chapter.idx,
            Chapter.title,
            Chapter.char_count,
            Translation.id,
            Translation.pieces_done,
            Translation.title,
        )
        .outerjoin(
            Translation,
            (Translation.chapter_id == Chapter.id)
            & (Translation.target_lang == target_lang),
        )
        .where(Chapter.novel_id == novel_id)
        .order_by(Chapter.idx)
    )
    rows: list[ChapterRow] = []
    for i, t, c, tr_id, pieces, tr_title in session.execute(stmt).all():
        has_row = tr_id is not None
        rows.append(
            ChapterRow(
                idx=i,
                title=t,
                char_count=c,
                translated=has_row and pieces is None,
                pieces_done=pieces if has_row else None,
                title_en=tr_title if has_row else None,
            )
        )
    return rows


def get_translation(
    session: Session, *, chapter_id: int, target_lang: str = "en"
) -> Translation | None:
    return session.execute(
        select(Translation).where(
            Translation.chapter_id == chapter_id,
            Translation.target_lang == target_lang,
        )
    ).scalar_one_or_none()


def untitled_translations(
    session: Session, novel_id: int, *, target_lang: str = "en"
) -> list[tuple[Translation, str]]:
    """(translation, source chapter title) for complete translations that have
    a source title but no translated title yet, in chapter order."""
    rows = session.execute(
        select(Translation, Chapter.title)
        .join(Chapter, Chapter.id == Translation.chapter_id)
        .where(
            Chapter.novel_id == novel_id,
            Translation.target_lang == target_lang,
            Translation.pieces_done.is_(None),
            Translation.text != "",
            Translation.title.is_(None),
            Chapter.title.is_not(None),
            Chapter.title != "",
        )
        .order_by(Chapter.idx)
    ).all()
    return [(tr, t) for tr, t in rows]


def update_novel(session: Session, novel_id: int, **fields) -> Novel | None:
    """Set only the fields given. Unknown keys are ignored, not an error."""
    novel = session.get(Novel, novel_id)
    if novel is None:
        return None
    allowed = {"title", "title_en", "author", "description", "tags", "status", "source_lang"}
    for key, value in fields.items():
        if key in allowed and value is not None:
            setattr(novel, key, value)
    session.flush()
    return novel


def delete_novel(session: Session, novel_id: int) -> bool:
    """Delete a novel and everything hanging off it.

    Chapters, translations, terms, relations and reading progress all cascade
    in the schema.
    """
    novel = session.get(Novel, novel_id)
    if novel is None:
        return False
    session.delete(novel)
    session.flush()
    return True


def update_term(
    session: Session,
    novel_id: int,
    term_id: int,
    *,
    target_term: str | None = None,
    locked: bool | None = None,
) -> Term | None:
    """Admin edit of one glossary entry. Editing the rendering locks it unless
    ``locked`` says otherwise."""
    t = session.get(Term, term_id)
    if t is None or t.novel_id != novel_id:
        return None
    if target_term is not None:
        t.target_term = target_term.strip()
        if locked is None:
            t.locked = True
    if locked is not None:
        t.locked = locked
    session.flush()
    return t


# --- Review flags ----------------------------------------------------------

def replace_open_flags(
    session: Session, novel_id: int, chapter_idx: int, flags: Iterable[dict]
) -> None:
    """Swap a chapter's open flags for a fresh set; resolved ones are kept."""
    session.execute(
        sa_delete(ReviewFlag).where(
            ReviewFlag.novel_id == novel_id,
            ReviewFlag.chapter_idx == chapter_idx,
            ReviewFlag.status == "open",
        )
    )
    for f in flags:
        session.add(
            ReviewFlag(
                novel_id=novel_id,
                chapter_idx=chapter_idx,
                kind=f["kind"],
                source_span=f.get("source_span", ""),
                target_span=f.get("target_span", ""),
                note=f.get("note", ""),
            )
        )
    session.flush()


def list_flags(
    session: Session, novel_id: int, status: str | None, chapter: int | None
) -> Sequence[ReviewFlag]:
    q = select(ReviewFlag).where(ReviewFlag.novel_id == novel_id)
    if status:
        q = q.where(ReviewFlag.status == status)
    if chapter is not None:
        q = q.where(ReviewFlag.chapter_idx == chapter)
    return session.execute(q.order_by(ReviewFlag.chapter_idx, ReviewFlag.id)).scalars().all()


def resolve_flag(
    session: Session, flag_id: int, user_id: int, wrong_rendering: str | None = None
) -> ReviewFlag | None:
    """Close a flag. For glossary_drift, ``wrong_rendering`` teaches the fixer."""
    f = session.get(ReviewFlag, flag_id)
    if f is None:
        return None
    wr = (wrong_rendering or "").strip()
    if wr and f.kind == "glossary_drift":
        f.target_span = wr
    f.status = "resolved"
    f.resolved_by = user_id
    session.flush()
    return f


def load_variants(session: Session, novel_id: int) -> dict[str, list[str]]:
    """{source_term: [wrong renderings]} from earlier glossary_drift flags."""
    rows = session.execute(
        select(ReviewFlag.source_span, ReviewFlag.target_span).where(
            ReviewFlag.novel_id == novel_id,
            ReviewFlag.kind == "glossary_drift",
            ReviewFlag.target_span != "",
        )
    ).all()
    out: dict[str, list[str]] = {}
    for src, tgt in rows:
        if tgt not in out.setdefault(src, []):
            out[src].append(tgt)
    return out


# --- View stats and rankings ----------------------------------------------

RANK_WINDOW_DAYS = {"day": 1, "week": 7, "month": 30}


def record_view(
    session: Session, novel_id: int, day: date, *, new_reader: bool
) -> None:
    """Count one chapter view for ``day`` in a single upsert statement."""
    r = 1 if new_reader else 0
    ins = pg_insert(NovelDailyStat).values(
        novel_id=novel_id, day=day, views=1, readers=r
    )
    session.execute(
        ins.on_conflict_do_update(
            index_elements=[NovelDailyStat.novel_id, NovelDailyStat.day],
            set_={
                "views": NovelDailyStat.views + 1,
                "readers": NovelDailyStat.readers + r,
            },
        )
    )


def ranking_query(period: str, limit: int, today: date) -> Select:
    """(novel_id, views) for the top novels in the window, ties by id."""
    total = func.sum(NovelDailyStat.views).label("views")
    stmt = select(NovelDailyStat.novel_id, total).group_by(NovelDailyStat.novel_id)
    days = RANK_WINDOW_DAYS.get(period)
    if days is not None:
        stmt = stmt.where(NovelDailyStat.day > today - timedelta(days=days))
    return (
        stmt.having(total > 0)
        .order_by(total.desc(), NovelDailyStat.novel_id.asc())
        .limit(limit)
    )


def ranked_rows(
    session: Session, period: str, limit: int, today: date
) -> list[tuple[int, LibraryRow]]:
    """(views in window, row) in rank order."""
    top = session.execute(ranking_query(period, limit, today)).all()
    if not top:
        return []
    by_id = {
        r.novel.id: r
        for r in library_rows(session, CatalogParams(ids=tuple(i for i, _ in top)))
    }
    return [(int(v), by_id[i]) for i, v in top if i in by_id]
