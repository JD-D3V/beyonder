"use client";

import { useCallback, useEffect, useState } from "react";
import { errorText } from "../../lib/api";
import { AdminReport, Invite, siteApi } from "../../lib/api-site";
import { getSession, SESSION_EVENT, type Session } from "../../lib/session";

export default function AdminPage() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [reports, setReports] = useState<AdminReport[]>([]);
  const [days, setDays] = useState(7);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const sync = () => setSession(getSession());
    sync();
    window.addEventListener(SESSION_EVENT, sync);
    return () => window.removeEventListener(SESSION_EVENT, sync);
  }, []);

  const isAdmin = Boolean(session?.user.is_admin);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [i, r] = await Promise.all([siteApi.listInvites(), siteApi.listReports(false)]);
      setInvites(i);
      setReports(r);
    } catch (e) {
      setErr(errorText(e));
    }
  }, []);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  async function createInvite() {
    setErr(null);
    try {
      await siteApi.createInvite(days);
      setInvites(await siteApi.listInvites());
    } catch (e) {
      setErr(errorText(e));
    }
  }

  async function copy(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(code);
      setTimeout(() => setCopied((c) => (c === code ? null : c)), 1500);
    } catch {
      setErr("Could not copy to the clipboard.");
    }
  }

  async function act(r: AdminReport, del: boolean) {
    setBusy(r.id);
    setErr(null);
    try {
      if (del) {
        if (r.kind === "comment") await siteApi.deleteComment(r.target_id);
        else await siteApi.deleteReview(r.target_id);
      }
      await siteApi.resolveReport(r.id);
      setReports((rs) => rs.filter((x) => x.id !== r.id));
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  if (session === undefined) return <p className="muted">Loading...</p>;
  if (!isAdmin) {
    return (
      <div className="empty">
        <h3>Admins only</h3>
        <p>You need an admin account to see this page.</p>
      </div>
    );
  }

  return (
    <>
      <div className="page-head">
        <h1>Admin</h1>
      </div>
      {err && <div className="error">{err}</div>}

      <section className="admin-section">
        <h2>Invites</h2>
        <div className="row" style={{ gap: 8, marginBottom: 12 }}>
          <label className="small">
            Valid for{" "}
            <input
              type="number"
              min={1}
              max={90}
              value={days}
              onChange={(e) => setDays(Math.max(1, Number(e.target.value) || 1))}
              style={{ width: 70 }}
            />{" "}
            days
          </label>
          <button onClick={createInvite}>Create invite</button>
        </div>
        {invites.length === 0 && <p className="muted">No invites yet.</p>}
        <ul className="admin-list">
          {invites.map((i) => (
            <li key={i.code}>
              <code>{i.code}</code>
              <span className="muted small">
                {i.used ? "used" : `expires ${new Date(i.expires_at).toLocaleDateString()}`}
              </span>
              <button className="secondary" onClick={() => copy(i.code)}>
                {copied === i.code ? "Copied" : "Copy"}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="admin-section">
        <h2>Reports</h2>
        {reports.length === 0 && <p className="muted">No open reports.</p>}
        <ul className="admin-list">
          {reports.map((r) => (
            <li key={r.id} className="report-item">
              <div>
                <div className="small muted">
                  {r.kind} by {r.target_author ?? "unknown"} · reported by {r.reporter}
                  {r.reason ? ` · "${r.reason}"` : ""}
                </div>
                <div className="report-text">{r.target_body ?? "(already removed)"}</div>
              </div>
              <div className="row" style={{ gap: 6 }}>
                <button className="secondary" disabled={busy === r.id} onClick={() => act(r, false)}>
                  Resolve
                </button>
                {r.target_body != null && (
                  <button disabled={busy === r.id} onClick={() => act(r, true)}>
                    Delete {r.kind}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
