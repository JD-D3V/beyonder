import { Fragment, useMemo, type ReactNode } from "react";
import type { GlossaryEntry } from "../lib/api";
import { applyTextStyle, type BracketsStyle, type QuotesStyle } from "../lib/textStyle";

const WORD = /[\p{L}\p{N}_]/u;
const KINDS = new Set(["character", "sect", "realm", "technique", "item", "other"]);

// Whole-word: the characters on either side of a match must not be word chars
// (term edges that are themselves punctuation need no boundary check).
function boundaryOk(text: string, start: number, end: number, term: string): boolean {
  const first = term[0];
  const last = term[term.length - 1];
  if (WORD.test(first) && start > 0 && WORD.test(text[start - 1])) return false;
  if (WORD.test(last) && end < text.length && WORD.test(text[end])) return false;
  return true;
}

function highlight(
  text: string,
  byTarget: Map<string, GlossaryEntry>,
  byFirst: Map<string, string[]>,
  termColors: boolean,
): ReactNode[] {
  if (byTarget.size === 0) return [text];
  const out: ReactNode[] = [];
  let buf = "";
  let i = 0;
  let key = 0;
  while (i < text.length) {
    let hit: string | null = null;
    for (const term of byFirst.get(text[i]) ?? []) {
      if (text.startsWith(term, i) && boundaryOk(text, i, i + term.length, term)) {
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
      const cls = termColors ? `term term-${KINDS.has(e.kind) ? e.kind : "other"}` : "term";
      out.push(
        <abbr key={key++} className={cls} title={`${e.source_term} · ${e.kind}`}>
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
}

// Styles the text (quotes/brackets), splits it into <p> paragraphs on blank
// lines and wraps glossary target terms in <abbr class="term term-<kind>">.
// Longest terms win; matching is case-sensitive and whole-word. React nodes only.
export default function GlossaryText({
  text,
  terms,
  termColors = true,
  quotes = "regular",
  brackets = "corner",
}: {
  text: string;
  terms: GlossaryEntry[];
  termColors?: boolean;
  quotes?: QuotesStyle;
  brackets?: BracketsStyle;
}) {
  const paragraphs = useMemo<ReactNode[][]>(() => {
    const style = { quotes, brackets };
    const byTarget = new Map<string, GlossaryEntry>();
    for (const t of terms) {
      if (!t.target_term) continue;
      const styled = applyTextStyle(t.target_term, style);
      if (!byTarget.has(styled)) byTarget.set(styled, t);
    }
    // First character -> candidate terms, longest first, so each position only
    // checks terms that could start there.
    const byFirst = new Map<string, string[]>();
    for (const term of [...byTarget.keys()].sort((a, b) => b.length - a.length)) {
      const list = byFirst.get(term[0]);
      if (list) list.push(term);
      else byFirst.set(term[0], [term]);
    }
    return applyTextStyle(text, style)
      .split(/\n[ \t]*\n+/)
      .filter((p) => p.trim() !== "")
      .map((p) => highlight(p, byTarget, byFirst, termColors));
  }, [text, terms, termColors, quotes, brackets]);

  return (
    <>
      {paragraphs.map((nodes, pi) => (
        <p key={pi}>
          {nodes.map((n, i) => (
            <Fragment key={i}>{n}</Fragment>
          ))}
        </p>
      ))}
    </>
  );
}
