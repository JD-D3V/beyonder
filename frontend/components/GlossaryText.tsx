import { Fragment, useMemo, type ReactNode } from "react";
import type { GlossaryEntry } from "../lib/api";

const WORD = /[\p{L}\p{N}_]/u;

// Whole-word: the characters on either side of a match must not be word chars
// (term edges that are themselves punctuation need no boundary check).
function boundaryOk(text: string, start: number, end: number, term: string): boolean {
  const first = term[0];
  const last = term[term.length - 1];
  if (WORD.test(first) && start > 0 && WORD.test(text[start - 1])) return false;
  if (WORD.test(last) && end < text.length && WORD.test(text[end])) return false;
  return true;
}

// Wraps glossary target terms found in `text` in <abbr title="source · kind">.
// Longest terms win; matching is case-sensitive and whole-word.
export default function GlossaryText({
  text,
  terms,
}: {
  text: string;
  terms: GlossaryEntry[];
}) {
  const nodes = useMemo<ReactNode[]>(() => {
    const byTarget = new Map<string, GlossaryEntry>();
    for (const t of terms) {
      if (t.target_term && !byTarget.has(t.target_term)) byTarget.set(t.target_term, t);
    }
    if (byTarget.size === 0) return [text];
    const sorted = [...byTarget.keys()].sort((a, b) => b.length - a.length);

    const out: ReactNode[] = [];
    let buf = "";
    let i = 0;
    let key = 0;
    while (i < text.length) {
      let hit: string | null = null;
      for (const term of sorted) {
        if (
          text.startsWith(term, i) &&
          boundaryOk(text, i, i + term.length, term)
        ) {
          hit = term;
          break;
        }
      }
      if (hit) {
        if (buf) {
          out.push(buf);
          buf = "";
        }
        const e = byTarget.get(hit) as GlossaryEntry;
        out.push(
          <abbr key={key++} title={`${e.source_term} · ${e.kind}`}>
            {hit}
          </abbr>,
        );
        i += hit.length;
      } else {
        buf += text[i];
        i += 1;
      }
    }
    if (buf) out.push(buf);
    return out;
  }, [text, terms]);

  return (
    <>
      {nodes.map((n, i) => (
        <Fragment key={i}>{n}</Fragment>
      ))}
    </>
  );
}
