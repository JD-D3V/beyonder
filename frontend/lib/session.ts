// The signed-in session lives in this browser's local storage. The token is
// opaque to the page; the server decides what it is worth.

const KEY = "beyonder.session";
export const SESSION_EVENT = "beyonder:session";
// Fired on any 401 so the Nav can send the reader to the sign-in page.
export const UNAUTHORIZED_EVENT = "beyonder:unauthorized";

// A post-login destination is only honoured if it is a same-site path.
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return null;
  }
  return next;
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
