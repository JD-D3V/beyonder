"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { IconChevronLeft, IconFileText, IconLink, IconUpload } from "../../components/icons";
import { api, errorText, type Visibility } from "../../lib/api";
import { siteApi } from "../../lib/api-site";
import { getSession, SESSION_EVENT } from "../../lib/session";

type Mode = "file" | "paste" | "url" | "toc";

export default function ImportPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("file");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  // Set false on unmount so a running import poll stops.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Only admins can publish; everyone else's imports are private to them.
  const [isAdmin, setIsAdmin] = useState(false);
  const [visibility, setVisibility] = useState<Visibility>("private");
  useEffect(() => {
    const sync = () => setIsAdmin(Boolean(getSession()?.user.is_admin));
    sync();
    window.addEventListener(SESSION_EVENT, sync);
    return () => window.removeEventListener(SESSION_EVENT, sync);
  }, []);
  // Admins start on Public (the old behaviour); they can still pick Private.
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (isAdmin && !touched) setVisibility("public");
  }, [isAdmin, touched]);
  const chosen: Visibility = isAdmin ? visibility : "private";

  // Shared metadata
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [tags, setTags] = useState("");
  const [description, setDescription] = useState("");
  const [lang, setLang] = useState("");

  // Per-mode input
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [text, setText] = useState("");
  const [urls, setUrls] = useState("");
  const [tocUrl, setTocUrl] = useState("");
  const [maxChapters, setMaxChapters] = useState(200);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  function pick(f: File | null) {
    setFile(f);
    setErr(null);
    // A filename is a better default title than an empty box, and the user can
    // still overwrite it before saving.
    if (f && !title.trim()) {
      setTitle(f.name.replace(/\.[^.]+$/, ""));
    }
  }

  async function save() {
    setBusy(true);
    setErr(null);
    setDone(null);
    try {
      const tagList = tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);

      let novelId: number;
      if (mode === "toc") {
        const link = tocUrl.trim();
        if (!link) throw new Error("Add the table-of-contents URL.");
        const { job_id } = await siteApi.ingestToc({
          index_url: link,
          title: title.trim() || undefined,
          max_chapters: Math.min(500, Math.max(1, Math.round(maxChapters) || 200)),
          visibility: chosen,
        });
        setProgress({ done: 0, total: 0 });
        // Poll until the server has fetched every chapter.
        const deadline = Date.now() + 30 * 60 * 1000;
        let found: number | null = null;
        for (;;) {
          await new Promise((r) => setTimeout(r, 1500));
          if (!alive.current) return;
          if (Date.now() > deadline) {
            throw new Error("The import is taking too long. Check My imports later.");
          }
          const job = await siteApi.importJob(job_id);
          if (!alive.current) return;
          setProgress({ done: job.done, total: job.total });
          if (job.status === "failed") throw new Error(job.error || "The import failed.");
          if (job.status === "done") {
            found = job.novel_id;
            break;
          }
        }
        if (found == null) throw new Error("The import finished but no book was created.");
        novelId = found;
      } else if (mode === "file") {
        if (!file) throw new Error("Choose a .txt, .md or .epub file first.");
        const res = await api.uploadFile(file, {
          title: title.trim() || undefined,
          author: author.trim() || undefined,
          description: description.trim() || undefined,
          tags: tagList.join(",") || undefined,
          source_lang: lang.trim() || undefined,
          visibility: chosen,
        });
        novelId = res.novel_id;
      } else if (mode === "paste") {
        if (text.trim().length < 10) throw new Error("Paste some text first.");
        if (!title.trim()) throw new Error("Give the book a title.");
        const res = await api.ingestText({
          title: title.trim(),
          text,
          author: author.trim() || undefined,
          description: description.trim() || undefined,
          tags: tagList,
          source_lang: lang.trim() || undefined,
          visibility: chosen,
        });
        novelId = res.novel_id;
      } else {
        const list = urls
          .split("\n")
          .map((u) => u.trim())
          .filter(Boolean);
        if (list.length === 0) throw new Error("Add at least one URL.");
        if (!title.trim()) throw new Error("Give the book a title.");
        const res = await api.ingestUrl({
          title: title.trim(),
          urls: list,
          source_lang: lang.trim() || undefined,
          visibility: chosen,
        });
        novelId = res.novel_id;
      }
      setDone("Saved. Opening the book...");
      router.push(`/novel?id=${novelId}`);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Import a book</h1>
          <div className="sub">
            Anything you import is saved to your library and stays there.
            {isAdmin
              ? " Choose whether it is public or private."
              : " Your imports are private: only you can see them."}
          </div>
        </div>
        <Link href="/">
          <button className="secondary"><IconChevronLeft /> <span>Back to library</span></button>
        </Link>
      </div>

      <div className="tabs">
        <button
          className={`tab ${mode === "file" ? "active" : ""}`}
          onClick={() => setMode("file")}
        >
          <IconUpload /> <span>Upload a file</span>
        </button>
        <button
          className={`tab ${mode === "paste" ? "active" : ""}`}
          onClick={() => setMode("paste")}
        >
          <IconFileText /> <span>Paste text</span>
        </button>
        <button
          className={`tab ${mode === "url" ? "active" : ""}`}
          onClick={() => setMode("url")}
        >
          <IconLink /> <span>From URLs</span>
        </button>
        <button
          className={`tab ${mode === "toc" ? "active" : ""}`}
          onClick={() => setMode("toc")}
        >
          <IconLink /> <span>Table of contents URL</span>
        </button>
      </div>

      <div className="panel">
        {mode === "file" && (
          <div
            className={`dropzone ${dragOver ? "over" : ""}`}
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              pick(e.dataTransfer.files?.[0] ?? null);
            }}
          >
            <input
              ref={fileInput}
              type="file"
              accept=".txt,.md,.epub"
              style={{ display: "none" }}
              onChange={(e) => pick(e.target.files?.[0] ?? null)}
            />
            {file ? (
              <>
                <div className="picked">{file.name}</div>
                <div className="hint">
                  {(file.size / 1024).toFixed(0)} KB. Click to choose a different
                  file.
                </div>
              </>
            ) : (
              <>
                <div className="picked">Drop a file here, or click to choose</div>
                <div className="hint">
                  .txt, .md or .epub, up to 20 MB. Chapter headings are detected
                  automatically.
                </div>
              </>
            )}
          </div>
        )}

        {mode === "paste" && (
          <div className="field">
            <label>Text</label>
            <textarea
              style={{ minHeight: 260 }}
              placeholder="Paste a whole book or a single chapter. Chapter headings are detected."
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
        )}

        {mode === "url" && (
          <div className="field">
            <label>Chapter URLs, one per line</label>
            <textarea
              style={{ minHeight: 160 }}
              placeholder="One chapter URL per line"
              value={urls}
              onChange={(e) => setUrls(e.target.value)}
            />
            <div className="small muted">
              The server fetches these without running JavaScript, so pages that
              build their text in the browser come back empty. Personal use only.
            </div>
          </div>
        )}

        {mode === "toc" && (
          <>
            <div className="field">
              <label>Table of contents URL</label>
              <input
                type="url"
                placeholder="https://example.com/book/123/"
                value={tocUrl}
                onChange={(e) => setTocUrl(e.target.value)}
              />
            </div>
            <div className="field">
              <label>Maximum chapters (1 to 500)</label>
              <input
                type="number"
                min={1}
                max={500}
                value={maxChapters}
                onChange={(e) => setMaxChapters(Number(e.target.value))}
              />
              <div className="small muted">
                The server follows the chapter links on that page in order and
                fetches one chapter per second, so a long book takes a while. Keep
                this page open to see progress, or come back later; the import
                continues on the server. Personal use only.
              </div>
            </div>
            {progress && (
              <div className="field">
                <progress
                  value={progress.done}
                  max={Math.max(progress.total, 1)}
                  style={{ width: "100%" }}
                />
                <div className="small muted">
                  {progress.total
                    ? `Fetched ${progress.done} of ${progress.total} chapters`
                    : "Starting..."}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="panel">
        <div className="grid-2">
          <div className="field">
            <label>
              Title{mode === "file" ? " (defaults to the filename)" : ""}
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title"
            />
          </div>
          <div className="field">
            <label>Author</label>
            <input
              type="text"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              placeholder="Optional"
            />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label>Tags, comma separated</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="xianxia, cultivation"
            />
          </div>
          <div className="field">
            <label>Source language</label>
            <input
              type="text"
              value={lang}
              onChange={(e) => setLang(e.target.value)}
              placeholder="Detected automatically"
            />
          </div>
        </div>
        <div className="field">
          <label>Visibility</label>
          {isAdmin ? (
            <select
              value={visibility}
              onChange={(e) => {
                setTouched(true);
                setVisibility(e.target.value as Visibility);
              }}
              aria-label="Visibility"
            >
              <option value="public">Public: listed in the catalog for everyone</option>
              <option value="private">Private: only you and admins</option>
            </select>
          ) : (
            <div className="small muted">
              <span className="pill">Private</span> Only you (and admins) can see
              and read this book.
            </div>
          )}
        </div>
        <div className="field">
          <label>Description</label>
          <textarea
            style={{ minHeight: 80, fontFamily: "inherit" }}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional blurb"
          />
        </div>

        {err && <div className="error">{err}</div>}
        {done && <div className="notice">{done}</div>}

        <div className="row" style={{ marginTop: 12 }}>
          <button onClick={save} disabled={busy}>
            {busy ? "Saving..." : "Save to library"}
          </button>
          <span className="small muted">
            Importing only stores the text. Translation and search run later, per
            chapter, so nothing burns model quota at import time.
          </span>
        </div>
      </div>
    </>
  );
}
