"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import {
  clearToken,
  getToken,
  setToken,
  UNAUTHORIZED_EVENT,
} from "../lib/auth";

// Shown whenever the API answers 401, from any page. The token lives only in
// this browser, so each device unlocks once.
export default function TokenGate() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const onUnauthorized = () => {
      setValue(getToken());
      setOpen(true);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  if (!open) return null;

  async function unlock() {
    setChecking(true);
    setErr(null);
    const candidate = value.trim();
    if (!candidate) {
      setErr("Paste the access token first.");
      setChecking(false);
      return;
    }
    setToken(candidate);
    try {
      // Any guarded endpoint proves the token; the library list is the one the
      // user is about to need anyway.
      await api.listNovels();
      setOpen(false);
      // Re-run whatever the page was doing with the token now in place.
      window.location.reload();
    } catch {
      clearToken();
      setErr("That token was not accepted.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="gate-backdrop" role="dialog" aria-modal="true">
      <div className="gate">
        <h2>This library is private</h2>
        <p className="small muted">
          Enter the access token to use it. It is stored in this browser only,
          so each device asks once.
        </p>
        <input
          type="password"
          value={value}
          autoFocus
          placeholder="Access token"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") unlock();
          }}
        />
        {err && <div className="error">{err}</div>}
        <div className="row">
          <button onClick={unlock} disabled={checking}>
            {checking ? "Checking..." : "Unlock"}
          </button>
        </div>
      </div>
    </div>
  );
}
