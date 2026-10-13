# WTR-LAB-style reader settings — contract

Date: 2026-10-07 · Branch: `redo/wtr-style` · Frontend only. Four agents build this in parallel;
each owns the files listed for it and consumes the others only through the names below.

## Shared types (`frontend/lib/readerPrefs.ts`, owned by Agent A)

```ts
export type ReaderFont = "nunito" | "roboto" | "lora" | "lexend" | "atkinson" | "serif" | "sans";
export type ReaderTheme = "white" | "cream" | "tan" | "blue" | "pink" | "green" | "dark" | "custom";
export type ReaderType = "single" | "infinite";
export type QuotesStyle = "regular" | "smart";
export type BracketsStyle = "corner" | "regular" | "semicorner"; // 【】 [] 『』
export type TextAlign = "left" | "justify";

export interface ReaderPrefs {
  font: ReaderFont;          // default "lora"
  size: number;              // 12..32, step 1, default 18
  lineHeight: number;        // 1.2..2.4, step 0.1, default 1.8 ("Default" button resets to 1.8)
  width: number;             // 520..1100 px, default 760
  paragraphSpacing: number;  // 0..2 em, step 0.25, default 1
  align: TextAlign;          // default "left"
  theme: ReaderTheme;        // default "dark"
  customBg: string;          // "#rrggbb", default "#1b1b1f"
  customFg: string;          // "#rrggbb", default "#e8e6e3"
  termColors: boolean;       // default true
  readerType: ReaderType;    // default "single"
  quotes: QuotesStyle;       // default "regular"
  brackets: BracketsStyle;   // default "corner"
}
export const PREFS_KEY = "beyonder.reader";            // same key; loadPrefs migrates old values:
// old font "serif"/"sans" kept as-is; old theme "light"→"white", "sepia"→"tan", "dark"→"dark".
export const DEFAULT_PREFS: ReaderPrefs;
export function loadPrefs(): ReaderPrefs;               // validates/clamps every field; hex colors /^#[0-9a-f]{6}$/i
export function savePrefs(p: ReaderPrefs): void;
export const FONT_STACKS: Record<ReaderFont, string>;   // CSS font-family values using the CSS variables below
```

CSS variables applied by the reader page on `.reader-root` (existing names kept, new ones added):
`--r-font`, `--r-size`, `--r-lh`, `--r-width`, `--r-para` (paragraph spacing, e.g. `1em`), `--r-align`;
theme via `data-theme={prefs.theme}`; for `custom`, also inline `--r-bg`, `--r-page`, `--r-fg`
(page = bg, muted derived by the page from fg at 70% opacity via `color-mix`).

## Fonts (`frontend/lib/fonts.ts`, owned by Agent A)

`next/font/google` for Nunito, Roboto, Lora, Lexend, Atkinson Hyperlegible (latin, `display: "swap"`,
each with a CSS `variable`: `--font-nunito`, `--font-roboto`, `--font-lora`, `--font-lexend`,
`--font-atkinson`). Export `export const fontVariables: string` (space-joined `.variable` class names).
Fonts are downloaded at build time and self-hosted — no runtime requests to Google.

## Agent A — prefs + settings panel
Owns: `lib/readerPrefs.ts`, `lib/fonts.ts`, `components/ReaderSettings.tsx`, new `app/reader.css`
(all reader-theme CSS: the 8 `[data-theme]` palettes scoped to `.reader-root`, settings panel styles,
paragraph spacing/alignment rules for `.reader-text p`). Agent A does NOT edit `globals.css`
or `layout.tsx`; Agent D deletes the old `--r-*` reader palette blocks from `globals.css` and imports
`./reader.css` in `layout.tsx`.
`ReaderSettings` keeps its props `{prefs, onChange, onClose}` and adds optional
`view?: "translation"|"source"|"both"`, `onViewChange?: (v) => void`.
Panel layout like WTR-LAB: bottom sheet on narrow screens, side panel ≥ 900px, tabs **Display** |
**Settings** + button **Advanced**:
- Display: Font (5 named fonts + Serif + Sans as segmented buttons showing each in its own font),
  Font size `A-` [value] `A+`, Line height `Height -` [Default] `Height +`, Term colors Enabled/Disabled.
- Settings: Reader theme swatches (8; each shows "Aa" in its colors; custom shows a palette icon),
  Reader type Single Page / Infinite, View Translation / Source / Both (if props given).
- Advanced dialog: Quotes Regular/Smart, Brackets 【Corner】/[Regular]/『Semi-Corner』, Width slider,
  Paragraph spacing slider, Alignment Left/Justify, Custom theme (enable → sets theme "custom";
  `<input type=color>` for background/text; Reset to default), live Preview paragraph rendered with
  the current prefs (uses `applyTextStyle` from Agent B), Cancel / Save (Advanced edits a draft).

## Agent B — text styling + term colors
Owns: `components/GlossaryText.tsx`, new `lib/textStyle.ts`.
`export function applyTextStyle(text: string, opts: {quotes: QuotesStyle; brackets: BracketsStyle}): string`
— smart quotes convert straight `"`/`'` to “ ” ‘ ’ (apostrophes inside words → ’); regular converts curly
back to straight. Brackets: normalise any of 【】 [] 『』 to the chosen pair (only bracket pairs, not
other punctuation). Pure function, unit-testable by reading.
`GlossaryText` props become `{text, terms, termColors?: boolean, quotes?: QuotesStyle, brackets?: BracketsStyle}`
(defaults: true, "regular", "corner"). Applies `applyTextStyle` before matching (glossary targets are
also styled so matching still works). Renders paragraphs as `<p>` inside its output (split on blank
lines) so paragraph spacing applies. With `termColors`, each term gets class `term term-<kind>`
(kinds: character, sect, realm, technique, item, other); without, class `term` only (underline).
Term color CSS lives in `components/GlossaryText` → put rules in `app/reader.css`? No: Agent B adds
them to a new `app/terms.css` that Agent D imports in layout. Colors must read well on both light and
dark reader themes (use `color-mix` with `--r-fg`).

## Agent C — reader page + infinite mode
Owns: `app/reader/page.tsx`.
Wire the new prefs: CSS vars above (`FONT_STACKS[prefs.font]`), custom theme vars, pass
`termColors/quotes/brackets` to every `GlossaryText`, pass `view/onViewChange` to `ReaderSettings`.
Add a floating bottom toolbar like WTR-LAB (Prev · Ch. N / total · Next · Display/Settings button).
Infinite mode (`prefs.readerType === "infinite"`): render the current chapter, then append following
chapters as the reader nears the bottom (IntersectionObserver sentinel, 600px rootMargin), each with
its own heading (use `displayTitle`) and a divider; update the URL `ch` param with
`history.replaceState` (keep base path) and the "Ch. N / total" display as each chapter's heading
crosses the top; server progress advances naturally because each chapter is fetched with
`api.getChapter`. Untranslated chapters in infinite mode show a compact "Not translated yet" card
with the Translate button (signed in) instead of stopping the stream; stop appending at the last
chapter. Keyboard ←/→ still jump chapters (reset the stream to that chapter). Single mode unchanged.
Keep all existing behaviours (translate step loop + cancellation, ask panel, flags marker, bookmark,
prefs layout effect).

## Agent D — site light/dark theme + layout
Owns: `app/layout.tsx`, `app/globals.css` (site tokens only — do not touch `--r-*` blocks, Agent A
removes those), `components/Nav.tsx`, new `lib/siteTheme.ts`.
`siteTheme.ts`: `type SiteTheme = "light" | "dark" | "system"`, key `beyonder.siteTheme`, default
"system", `loadSiteTheme()`, `saveSiteTheme()`, `applySiteTheme(t)` sets
`document.documentElement.dataset.theme` to "light"/"dark" (system → matchMedia).
`globals.css`: keep current dark values as `:root`/`[data-theme="dark"]`; add a full light palette
under `[data-theme="light"]` and `@media (prefers-color-scheme: light)` for `:root:not([data-theme])`.
Fix inputs/selects/textarea to use tokens (the catalog search box currently renders white-on-dark).
`layout.tsx`: import `./reader.css` and `./terms.css` (create empty placeholder files if they don't
exist yet in your worktree, so the build passes — the other agents' versions replace them on merge),
apply `fontVariables` from `../lib/fonts` to `<body>` (create a minimal placeholder `lib/fonts.ts`
exporting `fontVariables = ""` if absent in your worktree), and add a tiny inline `<script>` in
`<head>` that applies the stored site theme before paint (no flash; wrap in try/catch).
`Nav.tsx`: add a Light/Dark/System toggle (IconSun/IconMoon), and the Settings page gets a
"Website theme" section too (`app/settings/page.tsx` is also owned by D).

## Shared rules
- If a file owned by another agent is missing or still old in your worktree, create a minimal
  placeholder matching this contract (first line `// placeholder: replaced on merge`) so your build
  passes. Never put real logic in another agent's file.
- Never run npm/pnpm/node/npx on the host. Verify with
  `docker compose --profile build run --rm frontend-build` (must pass) from your worktree.
- Placeholder files created only to make an isolated build pass must contain a first-line comment
  `// placeholder: replaced on merge` so the controller resolves conflicts to the real version.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
