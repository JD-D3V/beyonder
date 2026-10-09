"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import BookCover from "../../components/BookCover";
import { IconBookOpen, IconX } from "../../components/icons";
import { api, displayTitle, errorText, LibraryItem, LibraryOut, Shelf } from "../../lib/api";
import { SiteStats } from "../../lib/api-site";
import { getSession, SESSION_EVENT, type Session } from "../../lib/session";

const SHELVES: { key: Shelf; label: string }[] = [
  { key: "reading", label: "Reading" },
  { key: "plan", label: "Plan to read" },
  { key: "completed", label: "Completed" },
];

function LibraryBody() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [lib, setLib] = useState<LibraryOut | null>(null);
  const [shelf, setShelf] = useState<Shelf>("reading");
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    const sync = () => setSession(getSession());
    sync();
    window.addEventListener(SESSION_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(SESSION_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const signedIn = Boolean(session);

  const load = useCallback(async () => {
    setErr(null);
    try {
      setLib(await api.library());
    } catch (e) {
      setErr(errorText(e));
    }
  }, []);

  useEffect(() => {
    if (signedIn) load();
    else setLib(null);
  }, [signedIn, load]);

  async function move(n: LibraryItem, to: Shelf) {
    setBusyId(n.id);
    setErr(null);
    try {
      await api.setShelf(n.id, to);
      await load();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusyId(null);
    }
  }

  async function remove(n: LibraryItem) {
    setBusyId(n.id);
    setErr(null);
    try {
      await api.removeFromLibrary(n.id);
      await load();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusyId(null);
    }
  }

  if (session === undefined) return <p className="muted">Loading...</p>;

  if (!session) {
    return (
      <div className="empty">
        <h3>Your library</h3>
        <p>
          <Link href="/login">Sign in</Link> to keep shelves and your reading
          place. Or <Link href="/">browse the catalog</Link>.
        </p>
      </div>
    );
  }

  const items = lib ? lib[shelf] : [];

  return (
    <>
      <div className="page-head">
        <h1>Library</h1>
      </div>
      {err && <div className="error">{err}</div>}

      <div className="seg" style={{ marginBottom: 18, width: "fit-content" }}>
        {SHELVES.map((s) => (
          <button
            key={s.key}
            className={shelf === s.key ? "on" : ""}
            onClick={() => setShelf(s.key)}
          >
            {s.label}
            {lib ? ` (${lib[s.key].length})` : ""}
          </button>
        ))}
      </div>

      {!lib && !err && <p className="muted">Loading...</p>}

      {lib && items.length === 0 && (
        <div className="empty">
          <h3>Nothing here yet</h3>
          <p>
            Add books from <Link href="/">the catalog</Link>.
          </p>
        </div>
      )}

      <div className="shelf">
        {items.map((n) => {
          const pct = n.chapter_count
            ? Math.min(100, Math.round(((n.current_chapter + 1) / n.chapter_count) * 100))
            : 0;
          const st = n as LibraryItem & SiteStats;
          const fresh = Math.max(0, n.chapter_count - 1 - n.current_chapter);
          return (
            <div className="book-card" key={n.id}>
              <Link href={`/novel?id=${n.id}`}>
                <BookCover title={displayTitle(n.title, n.title_en).text} id={n.id} hasCover={Boolean(st.has_cover)} coverVersion={st.cover_version} />
                <div className="body">
                  <div className="title" title={displayTitle(n.title, n.title_en).hover}>{displayTitle(n.title, n.title_en).text}</div>
                  <div className="author">{n.author || "Unknown author"}</div>
                  {fresh > 0 && <span className="pill new-badge">{fresh} new</span>}
                  <div className="meter" aria-hidden="true">
                    <span style={{ width: `${pct}%` }} />
                  </div>
                  <div className="meter-label">
                    <span>
                      Ch {n.current_chapter + 1} / {n.chapter_count}
                    </span>
                    <span>{pct}%</span>
                  </div>
                </div>
              </Link>
              <div className="body lib-actions">
                <Link
                  className="small"
                  href={`/reader?novel=${n.id}&ch=${n.current_chapter}`}
                >
                  <IconBookOpen size={14} /> Continue
                </Link>
                <div className="row" style={{ gap: 6 }}>
                  <select
                    aria-label="Move to shelf"
                    value={shelf}
                    disabled={busyId === n.id}
                    onChange={(e) => move(n, e.target.value as Shelf)}
                  >
                    {SHELVES.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  <button
                    className="secondary icon-btn"
                    onClick={() => remove(n)}
                    disabled={busyId === n.id}
                    aria-label={`Remove ${displayTitle(n.title, n.title_en).text} from library`}
                    title="Remove from library"
                  >
                    <IconX size={14} />
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

export default function LibraryPage() {
  return <LibraryBody />;
}
