"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import BookCover from "../../components/BookCover";
import {
  IconBookOpen,
  IconCheck,
  IconFlag,
  IconLanguages,
  IconList,
  IconLock,
  IconLockOpen,
  IconPencil,
  IconSearch,
  IconX,
} from "../../components/icons";
import {
  api,
  ChapterRow,
  CRITIC_MAX_CHARS,
  GlossaryEntry,
  Novel,
  ReviewFlag,
  Shelf,
} from "../../lib/api";
import { getSession, SESSION_EVENT, type Session } from "../../lib/session";

const ANON_PROGRESS_KEY = "beyonder.anonProgress";

function readAnonProgress(novelId: number): number {
  try {
    const raw = window.localStorage.getItem(ANON_PROGRESS_KEY);
    if (!raw) return 0;
    const v = (JSON.parse(raw) as Record<string, unknown>)[String(novelId)];
    return typeof v === "number" && v >= 0 ? v : 0;
  } catch {
    return 0;
  }
}

type Tab = "chapters" | "glossary" | "flags";

function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function BookInner() {
  const params = useSearchParams();
  const router = useRouter();
  const novelId = Number(params.get("id") || "0");

  const [novel, setNovel] = useState<Novel | null>(null);
  const [chapters, setChapters] = useState<ChapterRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [running, setRunning] = useState(false);
  const [progressNote, setProgressNote] = useState<string | null>(null);
  const [resumeAt, setResumeAt] = useState(0);
  // A ref, not state: the loop below reads it between awaits and would
  // otherwise close over the value from the render that started it.
  const stopped = useRef(false);

  const [session, setSession] = useState<Session | null>(null);
  const tabParam = params.get("tab");
  const [tab, setTab] = useState<Tab>(
    tabParam === "flags" || tabParam === "glossary" ? tabParam : "chapters",
  );
  const [shelf, setShelf] = useState<Shelf | "">("");
  const [glossary, setGlossary] = useState<GlossaryEntry[] | null>(null);
  const [flags, setFlags] = useState<ReviewFlag[] | null>(null);
  const [flagStatus, setFlagStatus] = useState("open");
  const [wrongInputs, setWrongInputs] = useState<Record<number, string>>({});
  const [termEdits, setTermEdits] = useState<Record<number, string>>({});
  const isAdmin = Boolean(session?.user.is_admin);

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

  // Edit form
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [tags, setTags] = useState("");
  const [status, setStatus] = useState("ongoing");
  const [lang, setLang] = useState("");
  const [description, setDescription] = useState("");

  const load = useCallback(async () => {
    if (!novelId) return;
    try {
      const [n, ch] = await Promise.all([
        api.getNovel(novelId),
        api.listChapters(novelId),
      ]);
      setNovel(n);
      setChapters(ch);
      setTitle(n.title);
      setAuthor(n.author || "");
      setTags(n.tags.join(", "));
      setStatus(n.status);
      setLang(n.source_lang);
      setDescription(n.description || "");
    } catch (e) {
      setErr(String(e));
    }
  }, [novelId]);

  useEffect(() => {
    load();
  }, [load]);

  // Signed in: progress and shelf live on the server. Otherwise this
  // browser's own record (the reader writes it) is all there is.
  const signedIn = session !== null;
  useEffect(() => {
    if (!novelId) return;
    if (!signedIn) {
      setResumeAt(readAnonProgress(novelId));
      setShelf("");
      return;
    }
    api
      .getProgress(novelId)
      .then((p) => setResumeAt(p.current_chapter))
      .catch(() => undefined);
    api
      .library()
      .then((lib) => {
        const found = (["reading", "plan", "completed"] as Shelf[]).find((k) =>
          lib[k].some((n) => n.id === novelId),
        );
        setShelf(found || "");
      })
      .catch(() => undefined);
  }, [novelId, signedIn]);

  // The glossary depends on who is reading (server caps it at their
  // progress), so drop the cache on sign-in/out or a different novel.
  const userId = session?.user.id ?? null;
  useEffect(() => {
    setGlossary(null);
  }, [novelId, userId]);

  useEffect(() => {
    if (!novelId) return;
    if (tab === "glossary" && glossary === null) {
      api.glossary(novelId).then(setGlossary).catch((e) => setErr(String(e)));
    }
  }, [novelId, tab, glossary]);

  useEffect(() => {
    if (!novelId || tab !== "flags") return;
    setFlags(null);
    api.flags(novelId, flagStatus).then(setFlags).catch((e) => setErr(String(e)));
  }, [novelId, tab, flagStatus]);

  async function changeShelf(value: string) {
    const prev = shelf;
    setShelf(value as Shelf | "");
    try {
      if (value) await api.setShelf(novelId, value as Shelf);
      else await api.removeFromLibrary(novelId);
    } catch (e) {
      setShelf(prev);
      setErr(String(e));
    }
  }

  async function resolveFlag(f: ReviewFlag) {
    setErr(null);
    try {
      await api.resolveFlag(f.id, (wrongInputs[f.id] || "").trim() || undefined);
      setFlags((cur) => (cur ? cur.filter((x) => x.id !== f.id) : cur));
    } catch (e) {
      setErr(String(e));
    }
  }

  async function patchTerm(
    t: GlossaryEntry,
    body: { target_term?: string; locked?: boolean },
  ) {
    if (t.id == null) return;
    setErr(null);
    try {
      await api.patchGlossaryTerm(novelId, t.id, body);
      setGlossary((cur) =>
        cur
          ? cur.map((x) =>
              x.id === t.id
                ? {
                    ...x,
                    ...(body.target_term !== undefined
                      ? { target_term: body.target_term }
                      : {}),
                    ...(body.locked !== undefined ? { locked: body.locked } : {}),
                  }
                : x,
            )
          : cur,
      );
      setTermEdits((cur) => {
        const { [t.id as number]: _drop, ...rest } = cur;
        return rest;
      });
    } catch (e) {
      setErr(String(e));
    }
  }

  async function saveEdits() {
    setBusy(true);
    setErr(null);
    try {
      await api.patchNovel(novelId, {
        title: title.trim(),
        author: author.trim(),
        description: description.trim(),
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        status,
        source_lang: lang.trim() || undefined,
      });
      setEditing(false);
      setNote("Saved.");
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function embedAll() {
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      const res = await api.embed({ novel_id: novelId });
      setNote(`Indexed ${res.points} passages. Questions can search this book now.`);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  // Translate one chapter. Short chapters go through /translate (with the
  // critic); long ones loop /translate/step until complete, so a chapter too
  // big for one request finishes over several and never loses saved progress.
  async function translateOneChapter(c: ChapterRow) {
    if (c.char_count <= CRITIC_MAX_CHARS) {
      await api.translate({ novel_id: novelId, chapter_idx: c.idx });
      return;
    }
    setNote(
      `Chapter ${c.idx + 1} is long (${compactNumber(
        c.char_count,
      )} characters) — translating in resumable passes. The critic re-translate pass is skipped for chapters this size.`,
    );
    let stalls = 0;
    for (;;) {
      if (stopped.current) return;
      const r = await api.translateStep({ novel_id: novelId, chapter_idx: c.idx });
      if (r.complete) return;
      if (r.stalled) {
        stalls += 1;
        if (stalls > 8) {
          throw new Error(
            "Gemini kept returning nothing — likely the free daily quota. " +
              "Progress is saved; resume this later.",
          );
        }
        setProgressNote(`Chapter ${c.idx + 1}: rate-limited, waiting...`);
        await sleep(20000);
      } else {
        stalls = 0;
        setProgressNote(
          `Chapter ${c.idx + 1}: piece ${r.pieces_done}/${r.pieces_total}...`,
        );
        await sleep(4000); // pace under the 15 req/min free tier
      }
    }
  }

  // Client-orchestrated so each chapter is routed by size and saved before the
  // next starts. Stopping or a dropped connection never discards finished work.
  async function runChapters(list: ChapterRow[]) {
    setRunning(true);
    stopped.current = false;
    setErr(null);
    let done = 0;
    try {
      for (const c of list) {
        if (stopped.current) {
          setProgressNote(`Stopped. ${done} translated in this run.`);
          break;
        }
        await translateOneChapter(c);
        done += 1;
        await load();
        setProgressNote(`${done} of ${list.length} translated...`);
      }
      if (!stopped.current) {
        setProgressNote(
          `Finished. ${done} chapter${done === 1 ? "" : "s"} translated.`,
        );
      }
    } catch (e) {
      setErr(String(e));
      setProgressNote(`Stopped after ${done}. Saved progress is kept.`);
    } finally {
      setRunning(false);
      await load();
    }
  }

  function translateSome(limit: number) {
    return runChapters(chapters.filter((c) => !c.translated).slice(0, limit));
  }

  function translateAll() {
    return runChapters(chapters.filter((c) => !c.translated));
  }

  async function remove() {
    const ok = window.confirm(
      `Delete "${novel?.title}" and every chapter, translation and glossary term that came from it? This cannot be undone.`,
    );
    if (!ok) return;
    setBusy(true);
    try {
      await api.deleteNovel(novelId);
      router.push("/");
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  if (!novelId) {
    return (
      <div className="empty">
        <h3>No book chosen</h3>
        <p>
          Pick one from <Link href="/">the library</Link>.
        </p>
      </div>
    );
  }

  if (err && !novel) return <div className="error">{err}</div>;
  if (!novel) return <p className="muted">Loading...</p>;

  const pct = novel.chapter_count
    ? Math.round((novel.translated_count / novel.chapter_count) * 100)
    : 0;
  const untranslated = chapters.filter((c) => !c.translated).length;

  return (
    <>
      <div className="page-head">
        <div className="small muted">
          <Link href="/">Library</Link> / {novel.title}
        </div>
      </div>

      <div className="panel">
        <div className="book-head">
          <BookCover title={novel.title} id={novel.id} size="lg" />
          <div className="info">
            {editing ? (
              <>
                <div className="grid-2">
                  <div className="field">
                    <label>Title</label>
                    <input
                      type="text"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label>Author</label>
                    <input
                      type="text"
                      value={author}
                      onChange={(e) => setAuthor(e.target.value)}
                    />
                  </div>
                </div>
                <div className="grid-2">
                  <div className="field">
                    <label>Tags</label>
                    <input
                      type="text"
                      value={tags}
                      onChange={(e) => setTags(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label>Status</label>
                    <select
                      value={status}
                      onChange={(e) => setStatus(e.target.value)}
                    >
                      <option value="ongoing">Ongoing</option>
                      <option value="completed">Completed</option>
                      <option value="hiatus">Hiatus</option>
                    </select>
                  </div>
                </div>
                <div className="grid-2">
                  <div className="field">
                    <label>Source language</label>
                    <input
                      type="text"
                      value={lang}
                      onChange={(e) => setLang(e.target.value)}
                      placeholder="zh"
                    />
                  </div>
                  <div />
                </div>
                <div className="field">
                  <label>Description</label>
                  <textarea
                    style={{ minHeight: 80, fontFamily: "inherit" }}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
                <div className="row">
                  <button onClick={saveEdits} disabled={busy}>
                    <IconCheck /> <span>Save</span>
                  </button>
                  <button className="secondary" onClick={() => setEditing(false)}>
                    <IconX /> <span>Cancel</span>
                  </button>
                </div>
              </>
            ) : (
              <>
                <h1>{novel.title}</h1>
                <div className="muted">{novel.author || "Unknown author"}</div>
                <div className="pill-row">
                  <span className={`pill status-${novel.status}`}>
                    {novel.status}
                  </span>
                  <span className="pill">{novel.source_lang}</span>
                  {novel.tags.map((t) => (
                    <span className="pill" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
                {novel.description && <p>{novel.description}</p>}
                <div className="stat-row">
                  <div className="stat">
                    <span className="v">{novel.chapter_count}</span>
                    <span className="l">Chapters</span>
                  </div>
                  <div className="stat">
                    <span className="v">{compactNumber(novel.char_count)}</span>
                    <span className="l">Characters</span>
                  </div>
                  <div className="stat">
                    <span className="v">{pct}%</span>
                    <span className="l">Translated</span>
                  </div>
                </div>
                {signedIn && (
                  <div className="row">
                    <label className="small muted" htmlFor="shelf-select">
                      Shelf
                    </label>
                    <select
                      id="shelf-select"
                      value={shelf}
                      onChange={(e) => changeShelf(e.target.value)}
                      style={{ width: "auto" }}
                    >
                      <option value="">Not in my library</option>
                      <option value="reading">Reading</option>
                      <option value="plan">Plan to read</option>
                      <option value="completed">Completed</option>
                    </select>
                  </div>
                )}
                <div className="row">
                  <Link href={`/reader?novel=${novel.id}&ch=${resumeAt}`}>
                    <button>
                      <IconBookOpen />{" "}
                      <span>
                        {resumeAt > 0
                          ? `Continue from chapter ${resumeAt + 1}`
                          : "Start reading"}
                      </span>
                    </button>
                  </Link>
                  {signedIn && untranslated > 0 && (
                    <>
                      <button onClick={() => translateSome(3)} disabled={running}>
                        <IconLanguages /> <span>{running ? "Working..." : "Translate next 3"}</span>
                      </button>
                      <button
                        className="secondary"
                        onClick={translateAll}
                        disabled={running}
                      >
                        <IconLanguages /> <span>Translate all {untranslated}</span>
                      </button>
                    </>
                  )}
                  {running && (
                    <button
                      className="secondary"
                      onClick={() => {
                        stopped.current = true;
                      }}
                    >
                      <IconX /> <span>Stop</span>
                    </button>
                  )}
                  {signedIn && (
                    <button className="secondary" onClick={embedAll} disabled={busy}>
                      <IconSearch /> <span>{busy ? "Working..." : "Index for search"}</span>
                    </button>
                  )}
                  {isAdmin && (
                    <>
                      <button className="secondary" onClick={() => setEditing(true)}>
                        <IconPencil /> <span>Edit details</span>
                      </button>
                      <button className="secondary" onClick={remove} disabled={busy}>
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {err && <div className="error">{err}</div>}
      {note && <div className="notice">{note}</div>}
      {progressNote && <div className="notice">{progressNote}</div>}

      <div className="tabs">
        {(
          [
            ["chapters", "Chapters"],
            ["glossary", "Glossary"],
            ["flags", "Review flags"],
          ] as [Tab, string][]
        ).map(([k, label]) => {
          const TabIcon = k === "chapters" ? IconList : k === "glossary" ? IconLanguages : IconFlag;
          return (
          <button
            key={k}
            className={`tab ${tab === k ? "active" : ""}`}
            onClick={() => setTab(k)}
          >
            <TabIcon /> <span>{label}</span>
          </button>
          );
        })}
      </div>

      {tab === "glossary" && (
        <div className="panel">
          {glossary === null && <p className="muted">Loading...</p>}
          {glossary !== null && glossary.length === 0 && (
            <p className="muted">No glossary terms yet.</p>
          )}
          {glossary !== null && glossary.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Translation</th>
                  <th>Kind</th>
                  <th>From ch.</th>
                  {isAdmin && <th></th>}
                </tr>
              </thead>
              <tbody>
                {glossary.map((t, i) => {
                  const editable = isAdmin && t.id != null;
                  const draft = t.id != null ? termEdits[t.id] : undefined;
                  return (
                    <tr key={t.id ?? `${t.source_term}-${i}`}>
                      <td>{t.source_term}</td>
                      <td>
                        {editable && t.id != null ? (
                          <input
                            type="text"
                            value={draft ?? t.target_term}
                            onChange={(e) =>
                              setTermEdits((cur) => ({
                                ...cur,
                                [t.id as number]: e.target.value,
                              }))
                            }
                          />
                        ) : (
                          t.target_term
                        )}
                        {t.locked && (
                          <span className="pill">
                            <IconLock size={12} /> locked
                          </span>
                        )}
                      </td>
                      <td>{t.kind}</td>
                      <td>{t.first_chapter + 1}</td>
                      {isAdmin && (
                        <td>
                          {editable && (
                            <div className="row">
                              <button
                                className="secondary"
                                disabled={
                                  draft === undefined ||
                                  !draft.trim() ||
                                  draft.trim() === t.target_term
                                }
                                onClick={() =>
                                  patchTerm(t, { target_term: (draft || "").trim() })
                                }
                              >
                                <IconCheck /> <span>Save</span>
                              </button>
                              <button
                                className="secondary"
                                onClick={() => patchTerm(t, { locked: !t.locked })}
                              >
                                {t.locked ? <IconLockOpen /> : <IconLock />}{" "}
                                <span>{t.locked ? "Unlock" : "Lock"}</span>
                              </button>
                            </div>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "flags" && (
        <div className="panel">
          <div className="row" style={{ marginBottom: 10 }}>
            <select
              value={flagStatus}
              onChange={(e) => setFlagStatus(e.target.value)}
              style={{ width: "auto" }}
              aria-label="Flag status"
            >
              <option value="open">Open</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>
          {flags === null && <p className="muted">Loading...</p>}
          {flags !== null && flags.length === 0 && (
            <p className="muted">No {flagStatus} flags.</p>
          )}
          {flags?.map((f) => (
            <div className="flag-item" key={f.id} style={{ padding: "10px 0" }}>
              <div className="small muted">
                <Link href={`/reader?novel=${novel.id}&ch=${f.chapter_idx}`}>
                  Chapter {f.chapter_idx + 1}
                </Link>{" "}
                · {f.kind.replace(/_/g, " ")}
              </div>
              {f.source_span && <div>Source: {f.source_span}</div>}
              {f.target_span && <div>Translation: {f.target_span}</div>}
              {f.note && <div className="small muted">{f.note}</div>}
              {isAdmin && f.status === "open" && (
                <div className="row" style={{ marginTop: 6 }}>
                  {f.kind === "glossary_drift" && (
                    <input
                      type="text"
                      placeholder="Wrong rendering (optional)"
                      value={wrongInputs[f.id] || ""}
                      onChange={(e) =>
                        setWrongInputs((cur) => ({ ...cur, [f.id]: e.target.value }))
                      }
                      style={{ width: 220 }}
                    />
                  )}
                  <button className="secondary" onClick={() => resolveFlag(f)}>
                    <IconCheck /> <span>Resolve</span>
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === "chapters" && (
      <div className="panel">
        <div className="page-head" style={{ marginBottom: 10 }}>
          <div>
            <h1 style={{ fontSize: 18 }}>Chapters</h1>
            <div className="sub">
              {novel.translated_count} of {novel.chapter_count} translated
            </div>
          </div>
        </div>
        {chapters.length === 0 && (
          <p className="muted">
            No chapters were parsed from this import. Check the source text.
          </p>
        )}
        <div className="chapter-list">
          {chapters.map((c) => (
            <Link
              className="chapter-row"
              key={c.idx}
              href={`/reader?novel=${novel.id}&ch=${c.idx}`}
            >
              <span className="num">{c.idx + 1}</span>
              <span className="name">{c.title || `Chapter ${c.idx + 1}`}</span>
              <span className="flag">{compactNumber(c.char_count)}</span>
              <span className={`flag ${c.translated ? "done" : ""}`}>
                {c.translated
                  ? "translated"
                  : c.pieces_done != null
                    ? `in progress (${c.pieces_done} done)`
                    : "source only"}
              </span>
            </Link>
          ))}
        </div>
      </div>
      )}
    </>
  );
}

export default function NovelPage() {
  return (
    <Suspense fallback={<p className="muted">Loading...</p>}>
      <BookInner />
    </Suspense>
  );
}
