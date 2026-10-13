"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import "../app/social.css";
import { ApiError, errorText } from "../lib/api";
import { Comment, social } from "../lib/api-social";
import type { Session } from "../lib/session";

function countAll(list: Comment[]): number {
  return list.reduce((n, c) => n + (c.deleted ? 0 : 1) + countAll(c.replies), 0);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString();
}

function postError(e: unknown): string {
  if (e instanceof ApiError && e.code === "too_many_posts") return e.message;
  return errorText(e);
}

function Composer({
  placeholder,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  placeholder: string;
  submitLabel: string;
  onSubmit: (body: string) => Promise<void>;
  onCancel?: () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go() {
    if (!text.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await onSubmit(text.trim());
      setText("");
    } catch (e) {
      setErr(postError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="social-form">
      <textarea
        maxLength={2000}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {err && <div className="error">{err}</div>}
      <div className="row">
        <button onClick={go} disabled={busy || !text.trim()}>
          {busy ? "Posting..." : submitLabel}
        </button>
        {onCancel && (
          <button className="secondary" onClick={onCancel}>
            Cancel
          </button>
        )}
        <span className="small muted">{text.length}/2000</span>
      </div>
    </div>
  );
}

// Comments for one chapter. Loads when mounted (or when expanded, if
// `collapsed`), so the infinite reader only fetches what is opened.
export default function ChapterComments({
  novelId,
  idx,
  session,
  collapsed = false,
}: {
  novelId: number;
  idx: number;
  session: Session | null;
  collapsed?: boolean;
}) {
  const [open, setOpen] = useState(!collapsed);
  const [items, setItems] = useState<Comment[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [replyTo, setReplyTo] = useState<number | null>(null);

  const uid = session?.user.id ?? null;
  const isAdmin = Boolean(session?.user.is_admin);

  const load = useCallback(async () => {
    try {
      setItems(await social.comments(novelId, idx));
      setErr(null);
    } catch (e) {
      setErr(errorText(e));
    }
  }, [novelId, idx]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  async function post(body: string, parentId?: number) {
    await social.postComment(novelId, idx, body, parentId);
    setReplyTo(null);
    await load();
  }

  async function remove(id: number) {
    if (!window.confirm("Delete this comment?")) return;
    try {
      await social.deleteComment(id);
      await load();
    } catch (e) {
      setErr(errorText(e));
    }
  }

  async function report(id: number) {
    const reason = window.prompt("Why are you reporting this comment? (optional)");
    if (reason === null) return;
    try {
      await social.report("comment", id, reason.slice(0, 500));
      setNote("Thanks, the comment was reported.");
    } catch (e) {
      setErr(errorText(e));
    }
  }

  function renderOne(c: Comment, top: boolean) {
    return (
      <div className="social-item" key={c.id}>
        <div className="meta">
          <b>{c.deleted ? "" : c.author}</b>
          <span>{fmtDate(c.created_at)}</span>
        </div>
        <div className="body" style={c.deleted ? { fontStyle: "italic", opacity: 0.6 } : undefined}>
          {c.body}
        </div>
        {!c.deleted && (
          <div className="acts">
            {session && top && (
              <button className="link-btn" onClick={() => setReplyTo(replyTo === c.id ? null : c.id)}>
                Reply
              </button>
            )}
            {session && c.user_id !== uid && (
              <button className="link-btn" onClick={() => report(c.id)}>
                Report
              </button>
            )}
            {session && (c.user_id === uid || isAdmin) && (
              <button className="link-btn" onClick={() => remove(c.id)}>
                Delete
              </button>
            )}
          </div>
        )}
        {replyTo === c.id && (
          <div style={{ marginTop: 8 }}>
            <Composer
              placeholder="Write a reply..."
              submitLabel="Reply"
              onSubmit={(b) => post(b, c.id)}
              onCancel={() => setReplyTo(null)}
            />
          </div>
        )}
        {c.replies.length > 0 && (
          <div className="social-replies">{c.replies.map((r) => renderOne(r, false))}</div>
        )}
      </div>
    );
  }

  const count = items ? countAll(items) : null;
  const label = `Comments${count != null ? ` (${count})` : ""}`;

  const body = (
    <>
      {err && <div className="error">{err}</div>}
      {note && <p className="small muted">{note}</p>}
      {session ? (
        <Composer
          placeholder="Add a comment..."
          submitLabel="Post comment"
          onSubmit={(b) => post(b)}
        />
      ) : (
        <p className="small muted">
          <Link href="/login">Sign in</Link> to comment.
        </p>
      )}
      {items === null && !err && <p className="small muted">Loading comments...</p>}
      {items && items.length === 0 && <p className="small muted">No comments yet.</p>}
      {items && items.map((c) => renderOne(c, true))}
    </>
  );

  if (collapsed) {
    return (
      <details
        className="chapter-comments"
        open={open}
        onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>{label}</summary>
        {open && body}
      </details>
    );
  }
  return (
    <div className="chapter-comments">
      <h3 style={{ fontSize: 16 }}>{label}</h3>
      {body}
    </div>
  );
}
