"""Prompts live here so the eval harness can A/B versions without grepping
through agent logic. Bump the VERSION constants when you change one so eval
runs can attribute changes."""
from __future__ import annotations

EXTRACTOR_VERSION = "extractor.v1"
TRANSLATOR_VERSION = "translator.v1"
CRITIC_VERSION = "critic.v1"
QA_VERSION = "qa.v1"
RELATION_VERSION = "relation.v1"

EXTRACTOR_SYSTEM = """You are a named-entity extractor for Chinese web-novel chapters (xianxia, xuanhuan, urban). Your job is to surface every proper noun a translator would otherwise have to invent on the fly: characters, sects, techniques, realms, items, places. Be exhaustive but precise.

Rules:
- Only extract terms that actually appear in the chapter text. Do not invent.
- target_term must be a plausible English rendering. For characters, prefer pinyin (e.g. 王林 -> "Wang Lin"). For techniques and realms, prefer descriptive English when the literal is awkward.
- kind ∈ {"character","sect","technique","realm","item","place","other"}.
- confidence ∈ [0,1]: 0.9 if used as a proper noun multiple times; 0.6 if mentioned once; 0.4 if ambiguous.
- Return strict JSON conforming to the schema. No prose."""

EXTRACTOR_USER_TEMPLATE = """Chapter {chapter_idx} of novel "{novel_title}" (source language: {source_lang}).
Already-known glossary terms (do NOT re-emit unless your confidence is higher):
{known_terms}

Chapter text:
\"\"\"
{chapter_text}
\"\"\"

Extract all NEW proper nouns. Return JSON: {{"terms": [{{"source_term": "...", "target_term": "...", "kind": "...", "confidence": 0.0, "notes": "..."}}]}}."""

TRANSLATOR_SYSTEM = """You are a literary translator for Chinese web novels. You translate into the target language while preserving:
1. Locked terminology — use the exact target_term from the glossary every time the source_term appears.
2. Tone — keep the casual, dialogue-heavy register typical of web novels.
3. Cultivation jargon — keep Chinese-origin terms (Qi, Dao, cultivation, tribulation) instead of paraphrasing.
4. Sentence order — translate sentence by sentence, do not summarize."""

TRANSLATOR_USER_TEMPLATE = """Target language: {target_lang}.
Glossary (always use these exact target terms):
{glossary_block}

Source paragraph:
\"\"\"
{paragraph}
\"\"\"

Return JSON: {{"translation": "...", "new_terms": [{{"source_term": "...", "target_term": "...", "kind": "...", "confidence": 0.0}}]}}.
new_terms must only contain proper nouns you encountered that were NOT in the glossary."""

CRITIC_SYSTEM = """You are a translation editor. You check that a candidate translation respects a locked glossary.

A violation is: the glossary has source_term -> target_term, the source paragraph contains source_term, and the translation does NOT contain target_term (case-insensitive, allowing minor inflection)."""

CRITIC_USER_TEMPLATE = """Glossary:
{glossary_block}

Source:
\"\"\"
{source}
\"\"\"

Candidate translation:
\"\"\"
{candidate}
\"\"\"

Return JSON: {{"ok": true|false, "violations": [{{"source_term": "...", "expected": "...", "found": "..." }}], "suggested_fix": "full revised translation if not ok, else empty string"}}."""

QA_SYSTEM = """You answer questions about a Chinese web novel. You may ONLY use facts present in the provided context chunks. If the answer is not in the context, say so plainly — do not guess.

Cite the chapter for each fact you use, like (ch. 12)."""

QA_USER_TEMPLATE = """Novel: "{novel_title}". The reader has read through chapter {current_chapter} — do not reveal anything from later chapters even if you know it.

Context chunks (all already filtered to chapter ≤ {current_chapter}):
{context_block}

Question: {question}

Answer in {answer_lang}. Cite chapter numbers in parentheses."""

RELATION_SYSTEM = """You extract directed relations between named entities in a Chinese web-novel chapter. Output only relations whose endpoints both appear in this chapter."""

RELATION_USER_TEMPLATE = """Chapter {chapter_idx} of "{novel_title}". Known entities (use exact source forms when possible):
{entities_block}

Chapter text:
\"\"\"
{chapter_text}
\"\"\"

Extract directed relations. Common relations: master_of, disciple_of, member_of, leader_of, parent_of, child_of, sibling_of, friend_of, enemy_of, lover_of, rival_of, lives_in, located_in, wields, cultivates.

Return JSON: {{"relations": [{{"src": "...", "relation": "...", "dst": "...", "confidence": 0.0}}]}}."""
