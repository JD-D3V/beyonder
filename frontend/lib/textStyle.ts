// Pure text-styling helpers for the reader (quotes + bracket normalisation).
// Types are identical to the ones Agent A exports from readerPrefs.ts.
export type QuotesStyle = "regular" | "smart";
export type BracketsStyle = "corner" | "regular" | "semicorner"; // 【】 [] 『』

const BRACKET_PAIRS: Record<BracketsStyle, [string, string]> = {
  corner: ["【", "】"],
  regular: ["[", "]"],
  semicorner: ["『", "』"],
};
const OPEN_BRACKETS = /[【\[『]/g;
const CLOSE_BRACKETS = /[】\]』]/g;

// A quote is "opening" when it follows the start of the text, whitespace, an
// opening bracket/quote or a dash.
const OPENER_CONTEXT = /[\s(\[{【『「<—–\-“‘]/;
const WORDCH = /[\p{L}\p{N}]/u;

function smartQuotes(text: string): string {
  let out = "";
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c !== '"' && c !== "'") {
      out += c;
      continue;
    }
    const prev = i > 0 ? text[i - 1] : "";
    const next = i + 1 < text.length ? text[i + 1] : "";
    const opening = (prev === "" || OPENER_CONTEXT.test(prev)) && next !== "" && !/\s/.test(next);
    if (c === '"') {
      out += opening ? "“" : "”";
    } else if (prev && next && WORDCH.test(prev) && WORDCH.test(next)) {
      out += "’"; // apostrophe inside a word
    } else {
      out += opening ? "‘" : "’";
    }
  }
  return out;
}

function regularQuotes(text: string): string {
  return text.replace(/[“”]/g, '"').replace(/[‘’]/g, "'");
}

export function applyTextStyle(
  text: string,
  opts: { quotes: QuotesStyle; brackets: BracketsStyle },
): string {
  const [open, close] = BRACKET_PAIRS[opts.brackets] ?? BRACKET_PAIRS.corner;
  const bracketed = text.replace(OPEN_BRACKETS, open).replace(CLOSE_BRACKETS, close);
  return opts.quotes === "smart" ? smartQuotes(bracketed) : regularQuotes(bracketed);
}
