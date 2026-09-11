# Gold data

Two files drive the eval harness. Both are small seed samples — extend them up
to the targets in the project README (50 Q&A, 500 terms) before reporting
numbers anywhere.

## `qa.jsonl`

One JSON object per line:

```json
{
  "novel_slug": "smoke",
  "current_chapter": 1,
  "question": "Which sect did Wang Lin join?",
  "gold_answer_contains": ["Azure Wood Sect", "Qingmu"],
  "must_cite_chapter": 1,
  "is_spoiler_probe": false
}
```

- `gold_answer_contains` — answer is correct if ANY of these substrings appear (case-insensitive).
- `must_cite_chapter` — if set, the citation set must include this chapter idx.
- `is_spoiler_probe` — true for "ask about something past current_chapter" probes. We measure the *leakage* rate, which should be 0%. For these rows, `gold_answer_contains` should match a refusal phrase.

## `terms.jsonl`

One JSON object per line:

```json
{"source_term": "王林", "expected_target": "Wang Lin", "kind": "character"}
```

Used to measure term-consistency rates of Beyonder vs DeepL on the same chapter
text. Run `python -m eval.run translate` to populate a side-by-side report.

## Novel slugs

The harness expects novels to be loaded under stable titles. Use `scripts/seed_demo.py` (TODO) to deterministically load the "smoke" novel so eval numbers are reproducible. For your own evals, ingest a longer novel and add its slug here.
