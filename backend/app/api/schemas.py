from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class NovelOut(BaseModel):
    id: int
    title: str
    source_lang: str
    source_url: Optional[str] = None
    chapter_count: int = 0


class IngestTextIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    text: str = Field(min_length=10)
    source_lang: Optional[str] = None  # auto-detect if missing
    source_url: Optional[str] = None


class IngestUrlIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    urls: list[str] = Field(min_length=1)
    source_lang: Optional[str] = None


class IngestResult(BaseModel):
    novel_id: int
    chapters_added: int


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
