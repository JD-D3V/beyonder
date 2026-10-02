from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class NovelOut(BaseModel):
    """A book as the library shelf shows it."""

    id: int
    title: str
    author: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    status: str = "ongoing"
    source_lang: str
    source_url: Optional[str] = None
    chapter_count: int = 0
    char_count: int = 0
    translated_count: int = 0
    updated_at: Optional[str] = None


class NovelPatch(BaseModel):
    """Edit book metadata. Omitted fields are left alone."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=512)
    author: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = Field(default=None, pattern="^(ongoing|completed|hiatus)$")
    source_lang: Optional[str] = Field(default=None, max_length=8)


class ChapterOut(BaseModel):
    """One row in a book's chapter list."""

    idx: int
    title: Optional[str] = None
    char_count: int = 0
    translated: bool = False  # complete only
    # Set while a resumable translation is mid-flight (pieces done so far).
    pieces_done: Optional[int] = None


class ChapterDetail(BaseModel):
    """A chapter to read: the source, and the saved translation if there is one."""

    idx: int
    title: Optional[str] = None
    char_count: int = 0
    source_text: str
    translation: Optional[str] = None
    translated_with: Optional[str] = None
    critic_passes: Optional[int] = None
    # A full translation exists. False when untranslated, or when a resumable
    # run is partway (``translation`` then holds the prefix done so far).
    complete: bool = False
    pieces_done: Optional[int] = None


class IngestTextIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=10)
    source_lang: Optional[str] = None  # auto-detect if missing
    source_url: Optional[str] = None
    author: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = None
    tags: Optional[list[str]] = None


class IngestUrlIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    urls: list[str] = Field(min_length=1)
    source_lang: Optional[str] = None


class IngestResult(BaseModel):
    novel_id: int
    chapters_added: int
    title: Optional[str] = None


class EmbedIn(BaseModel):
    novel_id: int
    from_chapter: int = 0
    to_chapter: Optional[int] = None  # inclusive


class EmbedResult(BaseModel):
    points: int


class TranslateIn(BaseModel):
    novel_id: int
    chapter_idx: int
    target_lang: str = "en"
    # Admin only: overwrite an existing complete translation.
    force: bool = False


class TranslateResult(BaseModel):
    chapter_idx: int
    translation: str
    new_terms: list["GlossaryEntryOut"] = Field(default_factory=list)
    critic_passes: int


class TranslateStepIn(BaseModel):
    """One resumable pass over a chapter. Call repeatedly until ``complete``."""

    novel_id: int
    chapter_idx: int
    target_lang: str = "en"
    # Admin only: discard a complete translation and start over. Send it on the
    # first call only; later calls resume the partial it created.
    force: bool = False


class TranslateStepResult(BaseModel):
    chapter_idx: int
    pieces_done: int
    pieces_total: int
    complete: bool
    # A piece came back empty this call (transient rate-limit / model outage).
    # No progress and nothing corrupted — pause and call again.
    stalled: bool = False
    # Terms first persisted this call (seed hits and any the model found).
    new_terms: list["GlossaryEntryOut"] = Field(default_factory=list)


class AskIn(BaseModel):
    novel_id: int
    question: str
    # Ignored: the server uses the stored per-account position.
    current_chapter: Optional[int] = None
    answer_lang: str = "en"
    top_k: int = 8


class CitationOut(BaseModel):
    chapter_idx: int
    char_start: int
    char_end: int
    text: str
    score: float


class AskOut(BaseModel):
    answer: str
    citations: list[CitationOut]


class GlossaryEntryOut(BaseModel):
    id: Optional[int] = None
    locked: bool = False
    source_term: str
    target_term: str
    kind: str
    first_chapter: int
    confidence: float


class KgNode(BaseModel):
    id: str
    label: str
    kind: str
    first_chapter: int


class KgEdge(BaseModel):
    src: str
    dst: str
    relation: str
    first_chapter: int


class KgOut(BaseModel):
    nodes: list[KgNode]
    edges: list[KgEdge]


class ProgressIn(BaseModel):
    novel_id: int
    current_chapter: int

class TranslateBatchIn(BaseModel):
    """Translate the next few untranslated chapters.

    Bounded on purpose. See the route for why there is no job queue.
    """

    novel_id: int
    limit: int = Field(default=3, ge=1, le=10)
    target_lang: str = "en"


class TranslateBatchResult(BaseModel):
    translated: list[int] = Field(default_factory=list)
    remaining: int = 0
    done: bool = False
    # Set when the run stopped early. Chapters already finished are still saved.
    error: Optional[str] = None


class ProgressOut(BaseModel):
    novel_id: int
    current_chapter: int


class GlossaryPatch(BaseModel):
    target_term: Optional[str] = Field(default=None, max_length=256)
    locked: Optional[bool] = None

    @field_validator("target_term")
    @classmethod
    def _strip_nonempty(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("target_term must not be blank")
        return v


TranslateResult.model_rebuild()
TranslateStepResult.model_rebuild()
