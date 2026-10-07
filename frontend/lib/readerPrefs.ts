// Reading preferences live in this browser only.

export type ReaderFont = "nunito" | "roboto" | "lora" | "lexend" | "atkinson" | "serif" | "sans";
export type ReaderTheme = "white" | "cream" | "tan" | "blue" | "pink" | "green" | "dark" | "custom";
export type ReaderType = "single" | "infinite";
export type QuotesStyle = "regular" | "smart";
export type BracketsStyle = "corner" | "regular" | "semicorner"; // 【】 [] 『』
export type TextAlign = "left" | "justify";

export interface ReaderPrefs {
  font: ReaderFont;
  size: number; // 12..32 px
  lineHeight: number; // 1.2..2.4
  width: number; // 520..1100 px
  paragraphSpacing: number; // 0..2 em, step 0.25
  align: TextAlign;
  theme: ReaderTheme;
  customBg: string; // "#rrggbb"
  customFg: string; // "#rrggbb"
  termColors: boolean;
  readerType: ReaderType;
  quotes: QuotesStyle;
  brackets: BracketsStyle;
}

export const PREFS_KEY = "beyonder.reader";

export const DEFAULT_PREFS: ReaderPrefs = {
  font: "lora",
  size: 18,
  lineHeight: 1.8,
  width: 760,
  paragraphSpacing: 1,
  align: "left",
  theme: "dark",
  customBg: "#1b1b1f",
  customFg: "#e8e6e3",
  termColors: true,
  readerType: "single",
  quotes: "regular",
  brackets: "corner",
};

export const FONT_STACKS: Record<ReaderFont, string> = {
  nunito: "var(--font-nunito), system-ui, sans-serif",
  roboto: "var(--font-roboto), system-ui, sans-serif",
  lora: 'var(--font-lora), Georgia, "Times New Roman", serif',
  lexend: "var(--font-lexend), system-ui, sans-serif",
  atkinson: "var(--font-atkinson), system-ui, sans-serif",
  serif: 'Georgia, "Iowan Old Style", "Times New Roman", serif',
  sans: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
};

export const FONT_LABELS: Record<ReaderFont, string> = {
  nunito: "Nunito",
  roboto: "Roboto",
  lora: "Lora",
  lexend: "Lexend",
  atkinson: "Atkinson",
  serif: "Serif",
  sans: "Sans",
};

export const THEME_ORDER: ReaderTheme[] = [
  "white",
  "cream",
  "tan",
  "blue",
  "pink",
  "green",
  "dark",
  "custom",
];

// Swatch colors for the settings panel; keep in sync with app/reader.css.
export const THEME_SWATCHES: Record<Exclude<ReaderTheme, "custom">, { bg: string; fg: string }> = {
  white: { bg: "#ffffff", fg: "#1f2328" },
  cream: { bg: "#f8f1e3", fg: "#3b3226" },
  tan: { bg: "#e6d8b8", fg: "#433422" },
  blue: { bg: "#dce8f5", fg: "#1c2b3d" },
  pink: { bg: "#f7e1e6", fg: "#3d2229" },
  green: { bg: "#dcebd9", fg: "#1f3322" },
  dark: { bg: "#1b1b1f", fg: "#e8e6e3" },
};

const HEX = /^#[0-9a-f]{6}$/i;
const FONTS: ReaderFont[] = ["nunito", "roboto", "lora", "lexend", "atkinson", "serif", "sans"];

function clampNum(v: unknown, min: number, max: number, fallback: number): number {
  return typeof v === "number" && Number.isFinite(v)
    ? Math.min(max, Math.max(min, v))
    : fallback;
}

function pick<T extends string>(v: unknown, allowed: readonly T[], fallback: T): T {
  return typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
}

export function loadPrefs(): ReaderPrefs {
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const p = JSON.parse(raw) as Record<string, unknown> | null;
    if (!p || typeof p !== "object") return { ...DEFAULT_PREFS };
    const D = DEFAULT_PREFS;
    // Old themes: light -> white, sepia -> tan.
    const legacy: Record<string, ReaderTheme> = { light: "white", sepia: "tan" };
    const theme: ReaderTheme =
      typeof p.theme === "string" && p.theme in legacy
        ? legacy[p.theme]
        : pick(p.theme, THEME_ORDER, D.theme);
    return {
      font: pick(p.font, FONTS, D.font),
      size: Math.round(clampNum(p.size, 12, 32, D.size)),
      lineHeight: Math.round(clampNum(p.lineHeight, 1.2, 2.4, D.lineHeight) * 10) / 10,
      width: clampNum(p.width, 520, 1100, D.width),
      paragraphSpacing:
        Math.round(clampNum(p.paragraphSpacing, 0, 2, D.paragraphSpacing) * 4) / 4,
      align: pick(p.align, ["left", "justify"] as const, D.align),
      theme,
      customBg: typeof p.customBg === "string" && HEX.test(p.customBg) ? p.customBg : D.customBg,
      customFg: typeof p.customFg === "string" && HEX.test(p.customFg) ? p.customFg : D.customFg,
      termColors: typeof p.termColors === "boolean" ? p.termColors : D.termColors,
      readerType: pick(p.readerType, ["single", "infinite"] as const, D.readerType),
      quotes: pick(p.quotes, ["regular", "smart"] as const, D.quotes),
      brackets: pick(p.brackets, ["corner", "regular", "semicorner"] as const, D.brackets),
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export function savePrefs(prefs: ReaderPrefs): void {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // storage blocked; preferences just won't persist
  }
}
