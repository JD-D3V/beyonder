// Reading preferences live in this browser only.

export interface ReaderPrefs {
  font: "serif" | "sans";
  size: number; // 14..26 px
  lineHeight: number; // 1.4..2.2
  width: number; // 560..960 px
  theme: "light" | "sepia" | "dark";
}

export const PREFS_KEY = "beyonder.reader";

export const DEFAULT_PREFS: ReaderPrefs = {
  font: "serif",
  size: 18,
  lineHeight: 1.8,
  width: 720,
  theme: "dark",
};

function clamp(v: unknown, min: number, max: number, fallback: number): number {
  return typeof v === "number" && Number.isFinite(v)
    ? Math.min(max, Math.max(min, v))
    : fallback;
}

export function loadPrefs(): ReaderPrefs {
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const p = JSON.parse(raw) as Partial<ReaderPrefs> | null;
    if (!p || typeof p !== "object") return { ...DEFAULT_PREFS };
    return {
      font: p.font === "sans" ? "sans" : "serif",
      size: clamp(p.size, 14, 26, DEFAULT_PREFS.size),
      lineHeight: clamp(p.lineHeight, 1.4, 2.2, DEFAULT_PREFS.lineHeight),
      width: clamp(p.width, 560, 960, DEFAULT_PREFS.width),
      theme:
        p.theme === "light" || p.theme === "sepia" || p.theme === "dark"
          ? p.theme
          : DEFAULT_PREFS.theme,
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
