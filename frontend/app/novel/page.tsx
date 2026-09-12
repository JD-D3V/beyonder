"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import BookCover from "../../components/BookCover";
import { api, ChapterRow, Novel } from "../../lib/api";

function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

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

  useEffect(() => {
    if (!novelId) return;
    api
      .getProgress(novelId)
      .then((p) => setResumeAt(p.current_chapter))
      .catch(() => undefined);
  }, [novelId]);

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

  async function translateSome(limit: number) {
    setRunning(true);
    stopped.current = false;
    setErr(null);
    setProgressNote("Translating...");
    try {
      const res = await api.translateBatch({ novel_id: novelId, limit });
      await load();
      if (res.error) {
        setErr(res.error);
        setProgressNote(
          `Stopped after ${res.translated.length}. ${res.remaining} chapter${
            res.remaining === 1 ? "" : "s"
          } left.`,
        );
      } else {
        setProgressNote(
          res.done
            ? "Every chapter is translated."
            : `${res.translated.length} done, ${res.remaining} to go.`,
        );
      }
    } catch (e) {
      setErr(String(e));
      setProgressNote(null);
    } finally {
      setRunning(false);
    }
  }

  async function translateAll() {
    setRunning(true);
    stopped.current = false;
    setErr(null);
    let done = 0;
    try {
      // Loop small batches rather than one long request: each batch is saved
      // before the next starts, so stopping or losing the connection never
      // throws away finished work.
      for (;;) {
        if (stopped.current) {
          setProgressNote(`Stopped. ${done} translated in this run.`);
          break;
        }
        const res = await api.translateBatch({ novel_id: novelId, limit: 3 });
        done += res.translated.length;
        await load();
        if (res.error) {
          setErr(res.error);
          setProgressNote(`Stopped after ${done}. ${res.remaining} left.`);
          break;
        }
        if (res.done) {
          setProgressNote(`Finished. ${done} chapter${done === 1 ? "" : "s"} translated.`);
          break;
        }
        setProgressNote(`${done} done, ${res.remaining} to go...`);
        if (res.translated.length === 0) {
          // Nothing moved and no error: stop rather than spin.
          break;
        }
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setRunning(false);
    }
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
                    Save
                  </button>
                  <button className="secondary" onClick={() => setEditing(false)}>
                    Cancel
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
                <div className="row">
                  <Link href={`/reader?novel=${novel.id}&ch=${resumeAt}`}>
                    <button>
                      {resumeAt > 0
                        ? `Continue from chapter ${resumeAt + 1}`
                        : "Start reading"}
                    </button>
                  </Link>
                  {untranslated > 0 && (
                    <>
                      <button onClick={() => translateSome(3)} disabled={running}>
                        {running ? "Working..." : "Translate next 3"}
                      </button>
                      <button
                        className="secondary"
                        onClick={translateAll}
                        disabled={running}
                      >
                        Translate all {untranslated}
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
                      Stop
                    </button>
                  )}
                  <button className="secondary" onClick={embedAll} disabled={busy}>
                    {busy ? "Working..." : "Index for search"}
                  </button>
                  <button className="secondary" onClick={() => setEditing(true)}>
                    Edit details
                  </button>
                  <Link href={`/glossary?novel=${novel.id}`}>
                    <button className="secondary">Glossary</button>
                  </Link>
                  <button className="secondary" onClick={remove} disabled={busy}>
                    Delete
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {err && <div className="error">{err}</div>}
      {note && <div className="notice">{note}</div>}
      {progressNote && <div className="notice">{progressNote}</div>}

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
                {c.translated ? "translated" : "source only"}
              </span>
            </Link>
          ))}
        </div>
      </div>
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
