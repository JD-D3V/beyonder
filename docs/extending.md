# Extending Beyonder

## Adding a new agent

1. Drop the prompt in `backend/app/agents/prompts.py`. Bump a `_VERSION` constant.
2. Write the agent function in a new file under `backend/app/agents/`. It should:
   - Take typed kwargs, not a dict.
   - Use `get_gemini()` for the LLM client (or accept an injected one).
   - Validate output with a JSON schema (see `extractor.py`).
   - Log a `done` event with a row count so eval scripts can count work.
3. Wire it into `graph/orchestrator.py` as a new node.
4. Export from `backend/app/agents/__init__.py`.

## Adding eval rows

`backend/eval/gold/qa.jsonl` and `terms.jsonl` are JSONL — one record per line.

Q&A row shape:
```json
{
  "novel_slug": "smoke",
  "current_chapter": 3,
  "question": "What did Wang Lin face in chapter 3?",
  "gold_answer_contains": ["tribulation", "thunder", "渡劫", "lightning"],
  "must_cite_chapter": 2,
  "is_spoiler_probe": false
}
```

For spoiler probes, set `is_spoiler_probe: true` and put refusal phrases in
`gold_answer_contains` (e.g. `["don't have", "no information"]`). The harness
counts the row as leaked when *none* of the refusal phrases appear.

## Adding a target language

The plan ships CN→EN baseline and stubs CN→JP. To add a new pair:

1. Make sure `detect_lang()` returns the source code you expect.
2. The translator agent already takes `target_lang` as a free string — Gemini
   handles arbitrary target languages.
3. Add the new option to `frontend/app/reader/page.tsx`'s `<select>`.
4. (Optional) Add a per-language glossary by setting `target_lang` on each
   `Term` row — `upsert_terms` already keys on `(novel_id, source_term, target_lang)`.

## Adding a Chrome extension overlay (stretch)

`frontend/` is a Next.js app, not an extension. To ship the Chrome overlay
mentioned in the plan, create `extension/` as a separate package using only
manifest v3 + a small content script that calls the backend `/translate`
endpoint. Keep it dependency-free (no npm) by writing vanilla JS. Same
security principle: ship hand-written code over a transitive-dep stack.

## Performance knobs

- `GEMINI_CONCURRENCY` (env): parallel agent calls. Default 3 keeps room
  inside the 15 RPM cap. Raise on a paid tier.
- `chunk_target_tokens` / `chunk_overlap_tokens` (config): bigger chunks ->
  fewer Qdrant points but blurrier retrieval.
- `critic_max_retries`: how many fix loops the critic does. Set to 0 to skip.

## Eval target promotion

Beyonder's resume bullet promises specific numbers (89% term consistency,
0% leakage). Don't quote these in your README until your `eval/run.py`
output beats them on your real gold sets:

1. Extend `terms.jsonl` to 500 hand-curated terms from a long novel.
2. Extend `qa.jsonl` to 50 Q&A items (and at least 10 spoiler probes).
3. Run `python -m eval.run all` repeatedly, iterating on the prompts in
   `agents/prompts.py` until you hit the targets.
4. Commit `eval/reports/run_TIMESTAMP.json` as evidence. The dashboard
   reads `eval/reports/latest.json` so the most recent always shows.
