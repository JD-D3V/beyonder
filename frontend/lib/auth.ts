// The site is a static export on a public host, so it cannot ship a secret:
// anything in the bundle is readable by anyone who opens the page. The access
// token is typed in once and kept in this browser's local storage instead, and
// a reader handle is generated the same way so reading position is per person
// without needing accounts.

const TOKEN_KEY = "beyonder.token";
const HANDLE_KEY = "beyonder.handle";

// Storage throws in some contexts (private windows, embedded previews, blocked
// site data), and a thrown getter would take the whole page down.
function read(key: string): string {
  try {
    return window.localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Nothing to do: the app still works for this session, it just forgets.
  }
}

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return read(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  write(TOKEN_KEY, token.trim());
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

export function getHandle(): string {
  if (typeof window === "undefined") return "demo";
  const existing = read(HANDLE_KEY);
  if (existing) return existing;
  const generated = `reader-${Math.random().toString(36).slice(2, 10)}`;
  write(HANDLE_KEY, generated);
  return generated;
}

export class UnauthorizedError extends Error {
  constructor(message = "This library is private.") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

// Any 401 anywhere should raise the unlock prompt, wherever the call was made
// from, so the gate listens for this rather than every page handling it.
export const UNAUTHORIZED_EVENT = "beyonder:unauthorized";

export function announceUnauthorized(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
}
