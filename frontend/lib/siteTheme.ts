export type SiteTheme = "light" | "dark" | "system";

export const SITE_THEME_KEY = "beyonder.siteTheme";
export const SITE_THEME_EVENT = "beyonder:site-theme";
export const DEFAULT_SITE_THEME: SiteTheme = "system";

export function loadSiteTheme(): SiteTheme {
  try {
    const v = window.localStorage.getItem(SITE_THEME_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    // Storage unavailable: fall back to the default.
  }
  return DEFAULT_SITE_THEME;
}

export function saveSiteTheme(t: SiteTheme): void {
  try {
    window.localStorage.setItem(SITE_THEME_KEY, t);
  } catch {
    // Ignore: the theme still applies for this page view.
  }
  window.dispatchEvent(new Event(SITE_THEME_EVENT));
}

export function resolveSiteTheme(t: SiteTheme): "light" | "dark" {
  if (t === "system") {
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  return t;
}

export function applySiteTheme(t: SiteTheme): void {
  document.documentElement.dataset.theme = resolveSiteTheme(t);
}
