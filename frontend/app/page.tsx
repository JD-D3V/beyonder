"use client";

import { useEffect, useState } from "react";
import { api, Novel } from "../lib/api";

export default function Home() {
  const [novels, setNovels] = useState<Novel[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [urlInput, setUrlInput] = useState("");

  async function refresh() {
    setErr(null);
    try {
      const xs = await api.listNovels();
      setNovels(xs);
    } catch (e: unknown) {
      setErr(String(e));
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onIngestText() {
    if (!title.trim() || !text.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.ingestText({ title, text });
      await api.embed({ novel_id: r.novel_id });
      setTitle("");
      setText("");
      await refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onIngestUrl() {
    if (!title.trim() || !urlInput.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const urls = urlInput
        .split(/\s+/)
        .map((u) => u.trim())
        .filter(Boolean);
      const r = await api.ingestUrl({ title, urls });
      await api.embed({ novel_id: r.novel_id });
      setTitle("");
      setUrlInput("");
      await refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Novels</h1>
      {err && <div className="error">{err}</div>}

      <div className="panel">
        <h3>Ingest text</h3>
        <div className="col">
          <input
            type="text"
            placeholder="Novel title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            placeholder="Paste raw text — chapter headers like 第一章 or Chapter 1 will be detected."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="row">
            <button disabled={busy} onClick={onIngestText}>
              {busy ? "Working..." : "Ingest + embed"}
            </button>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>Ingest from URL(s)</h3>
        <div className="col">
          <input
            type="text"
            placeholder="Novel title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            placeholder="One URL per line (each is a chapter page)"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
          />
          <div className="row">
            <button disabled={busy} onClick={onIngestUrl}>
              {busy ? "Working..." : "Scrape + embed"}
            </button>
            <span className="muted small">Personal use only — don't redistribute scraped novels.</span>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>Your library</h3>
        {novels.length === 0 ? (
          <p className="muted">No novels yet. Ingest one above.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Lang</th>
                <th>Chapters</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {novels.map((n) => (
                <tr key={n.id}>
                  <td>{n.id}</td>
                  <td>{n.title}</td>
                  <td>{n.source_lang}</td>
                  <td>{n.chapter_count}</td>
                  <td className="right">
                    <a href={`/reader?novel=${n.id}`}>Open</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
