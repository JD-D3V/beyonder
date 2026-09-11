"""Q&A agent — spoiler-aware retrieval + grounded answer."""
from __future__ import annotations

from dataclasses import dataclass

from ..common.logging import get_logger
from ..embed.gemini import GeminiClient, get_gemini
from ..embed.pipeline import embed_query
from ..embed.qdrant import SearchHit, search_chunks
from .prompts import QA_SYSTEM, QA_USER_TEMPLATE, QA_VERSION

log = get_logger(__name__)


@dataclass
class QAResult:
    answer: str
    citations: list[int]  # chapter indices used
    hits: list[SearchHit]


def _format_context(hits: list[SearchHit]) -> str:
    rows: list[str] = []
    for h in hits:
        snippet = h.text.strip().replace("\n", " ")
        if len(snippet) > 600:
            snippet = snippet[:600] + "..."
        rows.append(f"[ch.{h.chapter_idx}] {snippet}")
    return "\n\n".join(rows) if rows else "(no relevant chunks found)"


async def answer_question(
    *,
    question: str,
    novel_id: int,
    novel_title: str,
    current_chapter: int,
    answer_lang: str = "en",
    top_k: int = 8,
    client: GeminiClient | None = None,
) -> QAResult:
    qvec = await embed_query(question)
    hits = search_chunks(
        query_vec=qvec,
        novel_id=novel_id,
        max_chapter_idx=current_chapter,
        top_k=top_k,
    )
    if not hits:
        return QAResult(
            answer=(
                "I don't have any chapters of this novel within your reading "
                "progress that touch on this question."
            ),
            citations=[],
            hits=[],
        )

    user = QA_USER_TEMPLATE.format(
        novel_title=novel_title,
        current_chapter=current_chapter,
        context_block=_format_context(hits),
        question=question,
        answer_lang=answer_lang,
    )
    g = client or get_gemini()
    try:
        text = await g.generate(
            user,
            system=QA_SYSTEM,
            temperature=0.2,
            max_output_tokens=2048,
        )
    except Exception as e:
        log.warning("qa.fail", err=str(e), version=QA_VERSION)
        text = "Sorry — I couldn't reach the model just now. Try again."

    cits = sorted({h.chapter_idx for h in hits})
    return QAResult(answer=text, citations=cits, hits=hits)
