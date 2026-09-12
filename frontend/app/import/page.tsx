"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { api } from "../../lib/api";

type Mode = "file" | "paste" | "url";

export default function ImportPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("file");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

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
      if (mode === "file") {
        if (!file) throw new Error("Choose a .txt, .md or .epub file first.");
        const res = await api.uploadFile(file, {
          title: title.trim() || undefined,
          author: author.trim() || undefined,
          description: description.trim() || undefined,
          tags: tagList.join(",") || undefined,
          source_lang: lang.trim() || undefined,
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
        });
        novelId = res.novel_id;
      }
      setDone("Saved. Opening the book...");
      router.push(`/novel?id=${novelId}`);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Import a book</h1>
          <div className="sub">
            Anything you import is saved to your library and stays there.
          </div>
        </div>
        <Link href="/">
          <button className="secondary">Back to library</button>
        </Link>
      </div>

      <div className="tabs">
        <button
          className={`tab ${mode === "file" ? "active" : ""}`}
          onClick={() => setMode("file")}
        >
          Upload a file
        </button>
        <button
          className={`tab ${mode === "paste" ? "active" : ""}`}
          onClick={() => setMode("paste")}
        >
          Paste text
        </button>
        <button
          className={`tab ${mode === "url" ? "active" : ""}`}
          onClick={() => setMode("url")}
        >
          From URLs
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
