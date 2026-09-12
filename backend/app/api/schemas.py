from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
    translated: bool = False


class ChapterDetail(BaseModel):
    """A chapter to read: the source, and the saved translation if there is one."""

    idx: int
    title: Optional[str] = None
    char_count: int = 0
    source_text: str
    translation: Optional[str] = None
    translated_with: Optional[str] = None
    critic_passes: Optional[int] = None


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


class TranslateResult(BaseModel):
    chapter_idx: int
    translation: str
    new_terms: int
    critic_passes: int


class AskIn(BaseModel):
    novel_id: int
    question: str
    current_chapter: int
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
    handle: str = "demo"
    novel_id: int
    current_chapter: int
