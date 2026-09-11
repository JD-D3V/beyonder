"""Eval CLI.

Usage:
    python -m eval.run qa
    python -m eval.run translate
    python -m eval.run all

Writes a JSON report to eval/reports/latest.json plus a stamped copy.

Targets (see app/common/config.py):
    Q&A accuracy >= 85%
    Spoiler leakage <= 0%
    Term consistency >= 85%
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.agents.qa import answer_question  # noqa: E402
from app.agents.translator import translate_chapter  # noqa: E402
from app.common.config import settings  # noqa: E402
from app.common.logging import get_logger  # noqa: E402
from app.storage.db import get_session, init_engine  # noqa: E402
from app.storage.repository import (  # noqa: E402
    get_chapters,
    list_novels,
)
from eval.metrics import (  # noqa: E402
    QARowResult,
    QASummary,
    TermScore,
    score_qa,
    score_term_consistency,
)

log = get_logger("eval")

GOLD_DIR = REPO_ROOT / "eval" / "gold"
REPORT_DIR = REPO_ROOT / "eval" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("eval.bad_jsonl_line", path=str(path), line=line[:80])
    return out


def _resolve_novel_id(slug: str) -> int | None:
    with get_session() as s:
        for n in list_novels(s):
            if slug.lower() in n.title.lower():
                return n.id
    return None


async def run_qa() -> dict[str, Any]:
    rows_in = _load_jsonl(GOLD_DIR / "qa.jsonl")
    if not rows_in:
        return {"skipped": "qa.jsonl empty"}
    results: list[QARowResult] = []
    for row in rows_in:
        novel_id = _resolve_novel_id(row.get("novel_slug", ""))
        if novel_id is None:
            log.warning("eval.qa.no_novel", slug=row.get("novel_slug"))
            continue
        with get_session() as s:
            from app.storage.repository import get_novel

            novel = get_novel(s, novel_id)
            title = novel.title if novel else "Unknown"
        res = await answer_question(
            question=row["question"],
            novel_id=novel_id,
            novel_title=title,
            current_chapter=int(row.get("current_chapter", 0)),
            answer_lang=row.get("answer_lang", "en"),
        )
        correct, leaked = score_qa(
            answer=res.answer,
            gold_contains=row.get("gold_answer_contains", []),
            is_spoiler_probe=bool(row.get("is_spoiler_probe", False)),
        )
        cit_required = row.get("must_cite_chapter")
        cit_ok = None
        if cit_required is not None:
            cit_ok = int(cit_required) in res.citations
        results.append(
            QARowResult(
                question=row["question"],
                answer=res.answer,
                correct=correct,
                leaked=leaked,
                citation_ok=cit_ok,
                is_spoiler_probe=bool(row.get("is_spoiler_probe", False)),
            )
        )
    summary = QASummary.from_rows(results)
    return {
        "n": summary.n,
        "n_normal": summary.n_normal,
        "n_spoiler": summary.n_spoiler,
        "accuracy": round(summary.accuracy, 4),
        "spoiler_leakage": round(summary.spoiler_leakage, 4),
        "citation_accuracy": round(summary.citation_accuracy, 4),
        "targets": {
            "accuracy": settings.eval_target_qa_accuracy,
            "spoiler_leakage": settings.eval_target_spoiler_leakage,
        },
        "rows": [
            {
                "q": r.question,
                "a": r.answer[:400],
                "correct": r.correct,
                "leaked": r.leaked,
                "citation_ok": r.citation_ok,
                "is_spoiler_probe": r.is_spoiler_probe,
            }
            for r in results
        ],
    }


async def _translate_via_deepl(text: str, target: str = "EN-US") -> str:
    key = os.environ.get("DEEPL_API_KEY", "")
    if not key:
        return ""
    try:
        import deepl  # type: ignore

        translator = deepl.Translator(key)
        return str(translator.translate_text(text, target_lang=target).text)
    except Exception as e:
        log.warning("eval.deepl_fail", err=str(e))
        return ""


async def run_translate() -> dict[str, Any]:
    gold_terms = _load_jsonl(GOLD_DIR / "terms.jsonl")
    if not gold_terms:
        return {"skipped": "terms.jsonl empty"}

    with get_session() as s:
        novels = list(list_novels(s))
    if not novels:
        return {"skipped": "no novels ingested"}

    # Sample first novel's first 3 chapters as the test bed.
    novel = novels[0]
    with get_session() as s:
        chaps = list(get_chapters(s, novel.id))[:3]

    beyonder_samples: list[tuple[str, str]] = []
    deepl_samples: list[tuple[str, str]] = []

    # Build a glossary from gold for the translator
    glossary = [(g["source_term"], g["expected_target"]) for g in gold_terms]

    for chap in chaps:
        r = await translate_chapter(
            chap.source_text,
            glossary=list(glossary),
            target_lang="en",
            chapter_idx=chap.idx,
        )
        beyonder_samples.append((chap.source_text, r.translation))
        deepl_text = await _translate_via_deepl(chap.source_text)
        if deepl_text:
            deepl_samples.append((chap.source_text, deepl_text))

    def summarise(samples: list[tuple[str, str]]) -> dict[str, Any]:
        scores: list[TermScore] = []
        for g in gold_terms:
            scores.append(
                score_term_consistency(
                    source_term=g["source_term"],
                    expected_target=g["expected_target"],
                    samples=samples,
                )
            )
        scored = [s for s in scores if s.appearances > 0]
        rate = (
            sum(s.rate for s in scored) / len(scored) if scored else 0.0
        )
        return {
            "n_terms_observed": len(scored),
            "term_consistency": round(rate, 4),
            "per_term": [
                {
                    "source": s.source_term,
                    "expected": s.expected_target,
                    "appearances": s.appearances,
                    "consistent": s.consistent,
                    "rate": round(s.rate, 4),
                }
                for s in scored
            ],
        }

    return {
        "novel": novel.title,
        "chapters_sampled": len(chaps),
        "beyonder": summarise(beyonder_samples),
        "deepl": summarise(deepl_samples) if deepl_samples else {"skipped": "no DEEPL_API_KEY"},
        "targets": {"term_consistency": settings.eval_target_term_consistency},
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="Beyonder eval CLI")
    parser.add_argument("mode", choices=["qa", "translate", "all"])
    parser.add_argument("--out", type=Path, default=REPORT_DIR / "latest.json")
    args = parser.parse_args()

    init_engine()

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": settings.gemini_model,
    }

    if args.mode in ("qa", "all"):
        report["qa"] = await run_qa()
    if args.mode in ("translate", "all"):
        report["translate"] = await run_translate()

    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    stamped = REPORT_DIR / f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    stamped.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
