// The signed-in session lives in this browser's local storage. The token is
// opaque to the page; the server decides what it is worth.

const KEY = "beyonder.session";
export const SESSION_EVENT = "beyonder:session";

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
