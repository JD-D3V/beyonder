"""Thin data-access helpers. Keep agents/API code free of raw SQL.

Functions here take an open Session — they never open or commit their own.
"""
from __future__ import annotations

import json
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Chapter, Novel, Relation, Term, Translation, User


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
) -> Translation:
    existing = session.execute(
        select(Translation).where(
            Translation.chapter_id == chapter_id,
            Translation.target_lang == target_lang,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.text = text
        existing.model = model
        existing.critic_passes = critic_passes
        return existing
    tr = Translation(
        chapter_id=chapter_id,
        target_lang=target_lang,
        text=text,
        model=model,
        critic_passes=critic_passes,
    )
    session.add(tr)
    session.flush()
    return tr


# --- Terms ----------------------------------------------------------------

def upsert_terms(
    session: Session,
    *,
    novel_id: int,
    entries: Iterable[dict],
    target_lang: str = "en",
) -> list[Term]:
    """Insert or update terms. Higher-confidence wins on conflict."""
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

        existing = session.execute(
            select(Term).where(
                Term.novel_id == novel_id,
                Term.source_term == src,
                Term.target_lang == target_lang,
            )
        ).scalar_one_or_none()
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
            )
            session.add(t)
            out.append(t)
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


# --- Users ----------------------------------------------------------------

def get_or_create_user(session: Session, handle: str) -> User:
    u = session.execute(select(User).where(User.handle == handle)).scalar_one_or_none()
    if u is None:
        u = User(handle=handle, progress_json="{}")
        session.add(u)
        session.flush()
    return u


def get_user_chapter(session: Session, user: User, novel_id: int) -> int:
    try:
        prog = json.loads(user.progress_json or "{}")
    except json.JSONDecodeError:
        prog = {}
    return int(prog.get(str(novel_id), 0))


def set_user_chapter(
    session: Session, user: User, novel_id: int, chapter_idx: int
) -> None:
    try:
        prog = json.loads(user.progress_json or "{}")
    except json.JSONDecodeError:
        prog = {}
    prog[str(novel_id)] = int(chapter_idx)
    user.progress_json = json.dumps(prog)
