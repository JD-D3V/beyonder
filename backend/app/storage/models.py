"""SQLAlchemy 2.0 models. Mirrored by alembic migrations.

Schema design notes
-------------------
- ``novels`` is the unit users add. Library metadata (author, tags, status,
  description) lives here so the shelf view is one query. Raw text lives in Postgres for v1 (small per
  novel). If we outgrow it, move raw text to object storage and keep only
  metadata here.
- ``chapters`` keeps the canonical chapter order and the *source* text.
- ``translations`` is per (chapter, target_lang). Many-to-one with chapters.
- ``terms`` is the glossary. Has a pgvector ``embedding`` column so we can do
  semantic glossary search (catches surface variants like 渡劫/度劫).
- ``relations`` is the knowledge graph adjacency list. ``first_chapter`` is the
  spoiler key — drop relations whose first_chapter > user.current_chapter.
- ``users`` are invite-only accounts (one admin); ``sessions`` hold hashed bearer
  tokens, ``invites`` single-use signup codes, ``reading_progress`` the per-user
  spoiler key, ``library_entries`` personal shelves.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..common.config import settings


class Base(DeclarativeBase):
    pass


class Novel(Base):
    __tablename__ = "novels"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    # Translated (English) book title; NULL until translated or edited.
    title_en: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Comma-separated and lowercased. See the 0002 migration for why not a join.
    tags: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ongoing")
    source_lang: Mapped[str] = mapped_column(String(8), default="zh")
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="novel", cascade="all, delete-orphan"
    )
    terms: Mapped[list["Term"]] = relationship(
        back_populates="novel", cascade="all, delete-orphan"
    )
    relations: Mapped[list["Relation"]] = relationship(
        back_populates="novel", cascade="all, delete-orphan"
    )


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("novel_id", "idx", name="uq_chapter_novel_idx"),
        Index("ix_chapter_novel_idx", "novel_id", "idx"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    source_text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    novel: Mapped[Novel] = relationship(back_populates="chapters")
    translations: Mapped[list["Translation"]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )


class Translation(Base):
    __tablename__ = "translations"
    __table_args__ = (
        UniqueConstraint("chapter_id", "target_lang", name="uq_translation_chap_lang"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE")
    )
    target_lang: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    # Translated chapter title for this language; NULL until translated.
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    critic_passes: Mapped[int] = mapped_column(Integer, default=0)
    # Resumable translation progress. NULL means complete: both legacy rows and
    # single-pass (/translate) results, and any /translate/step run once its
    # last piece lands. A non-null value is the count of pieces translated so
    # far, and ``text`` holds the assembled prefix — a partial the next
    # /translate/step call resumes from.
    pieces_done: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    translated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    chapter: Mapped[Chapter] = relationship(back_populates="translations")


class Term(Base):
    __tablename__ = "terms"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "source_term", "target_lang", name="uq_term_novel_src_lang"
        ),
        Index("ix_term_novel", "novel_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    source_term: Mapped[str] = mapped_column(String(256))
    target_term: Mapped[str] = mapped_column(String(256))
    target_lang: Mapped[str] = mapped_column(String(8), default="en")
    kind: Mapped[str] = mapped_column(
        String(32), default="other"
    )  # character, sect, technique, realm, item, other
    first_chapter: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Locked terms are curated by an admin; automatic upserts never change them.
    locked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="terms")


class Relation(Base):
    __tablename__ = "relations"
    __table_args__ = (
        Index("ix_relation_novel_chap", "novel_id", "first_chapter"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    src_term: Mapped[str] = mapped_column(String(256))
    relation: Mapped[str] = mapped_column(String(64))  # e.g. master_of, member_of
    dst_term: Mapped[str] = mapped_column(String(256))
    first_chapter: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)

    novel: Mapped[Novel] = relationship(back_populates="relations")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Always stored lowercased and stripped (done in code, not the database).
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserSession(Base):
    """Named ``UserSession`` so it cannot be confused with sqlalchemy's Session."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invite(Base):
    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    used_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # used_by is SET NULL when the invitee is deleted; used_at is not, so a
    # claimed invite stays spent.
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReadingProgress(Base):
    __tablename__ = "reading_progress"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True
    )
    chapter_idx: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LibraryEntry(Base):
    __tablename__ = "library_entries"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True
    )
    shelf: Mapped[str] = mapped_column(String(16))  # reading | plan | completed
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewFlag(Base):
    """A non-blocking QA note on a translated chapter."""

    __tablename__ = "review_flags"
    __table_args__ = (
        Index("ix_review_flags_novel_status_chapter", "novel_id", "status", "chapter_idx"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    chapter_idx: Mapped[int] = mapped_column(Integer)
    # glossary_drift | unknown_name | pronoun | idiom | untranslated
    kind: Mapped[str] = mapped_column(String(24))
    source_span: Mapped[str] = mapped_column(Text, default="")
    target_span: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class NovelDailyStat(Base):
    """Per-novel, per-day view counters that feed the rankings."""

    __tablename__ = "novel_daily_stats"

    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    readers: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Review(Base):
    """One star rating (and optional text) per user per novel."""

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("novel_id", "user_id", name="uq_review_novel_user"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(Integer)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Comment(Base):
    """A chapter comment; replies are one level deep (parent_id of a top-level)."""

    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_novel_chapter_created", "novel_id", "chapter_idx", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    chapter_idx: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )


class ContentReport(Base):
    """A user's report of a review or comment, for admin triage."""

    __tablename__ = "content_reports"
    __table_args__ = (
        UniqueConstraint("kind", "target_id", "reporter_id", name="uq_report_once"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # review | comment
    target_id: Mapped[int] = mapped_column(Integer)
    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
