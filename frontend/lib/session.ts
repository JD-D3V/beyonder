// The signed-in session lives in this browser's local storage. The token is
// opaque to the page; the server decides what it is worth.

const KEY = "beyonder.session";
export const SESSION_EVENT = "beyonder:session";
// Fired on any 401 so the Nav can send the reader to the sign-in page.
export const UNAUTHORIZED_EVENT = "beyonder:unauthorized";

// A post-login destination is only honoured if it is a same-site path.
export function safeNext(next: string | null | undefined): string | null {
  const fallback = "/";
  if (typeof window === "undefined") return fallback;
  if (!next) return fallback;
  // Browsers strip tab/CR/LF inside URLs, so "/\t/evil.com" would become
  // "//evil.com". Reject control characters and backslashes outright.
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f\\]/.test(next)) return fallback;
  try {
    const u = new URL(next, window.location.origin);
    if (u.origin !== window.location.origin) return fallback;
    return u.pathname + u.search + u.hash;
  } catch {
    return fallback;
  }
}

export interface SessionUser {
  id: number;
  email: string;
  is_admin: boolean;
}

export interface Session {
  token: string;
  user: SessionUser;
}

function notify(): void {
  try {
    window.dispatchEvent(new CustomEvent(SESSION_EVENT));
  } catch {
    // ignore
  }
}

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    if (!s || typeof s.token !== "string" || !s.token || !s.user) return null;
    return s;
  } catch {
    return null;
  }
}

export function announceUnauthorized(): void {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
  } catch {
    // ignore
  }
}

export function setSession(session: Session): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // Storage blocked: the session just will not survive a reload.
  }
  notify();
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
  notify();
}
