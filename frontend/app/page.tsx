"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import BookCover from "../components/BookCover";
import { api, Novel } from "../lib/api";

type Sort = "recent" | "title" | "chapters" | "progress";

function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

export default function LibraryPage() {
  const [novels, setNovels] = useState<Novel[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [status, setStatus] = useState("all");

  useEffect(() => {
    api
      .listNovels()
      .then(setNovels)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    let out = novels.filter((n) => {
      if (status !== "all" && n.status !== status) return false;
      if (!q) return true;
      return (
        n.title.toLowerCase().includes(q) ||
        (n.author || "").toLowerCase().includes(q) ||
        n.tags.some((t) => t.includes(q))
      );
    });
    out = [...out].sort((a, b) => {
      if (sort === "title") return a.title.localeCompare(b.title);
      if (sort === "chapters") return b.chapter_count - a.chapter_count;
      if (sort === "progress") {
        const pa = a.chapter_count ? a.translated_count / a.chapter_count : 0;
        const pb = b.chapter_count ? b.translated_count / b.chapter_count : 0;
        return pb - pa;
      }
      return (b.updated_at || "").localeCompare(a.updated_at || "");
    });
    return out;
  }, [novels, query, sort, status]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <div className="sub">
            {loading
              ? "Loading..."
              : `${novels.length} book${novels.length === 1 ? "" : "s"}, ${compactNumber(
                  novels.reduce((s, n) => s + n.char_count, 0),
                )} characters of source text`}
          </div>
        </div>
        <Link href="/import">
          <button>Import a book</button>
        </Link>
      </div>

      {err && <div className="error">{err}</div>}

      {novels.length > 0 && (
        <div className="toolbar">
          <input
            className="grow"
            type="text"
            placeholder="Search title, author or tag"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">Any status</option>
            <option value="ongoing">Ongoing</option>
            <option value="completed">Completed</option>
            <option value="hiatus">Hiatus</option>
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="recent">Recently updated</option>
            <option value="title">Title</option>
            <option value="chapters">Most chapters</option>
            <option value="progress">Most translated</option>
          </select>
        </div>
      )}

      {!loading && novels.length === 0 && (
        <div className="empty">
          <h3>Nothing on the shelf yet</h3>
          <p>
            Import a .txt or .epub file, paste a chapter, or pull one from a URL.
            Whatever you add is saved and stays here.
          </p>
          <Link href="/import">
            <button>Import your first book</button>
          </Link>
        </div>
      )}

      {!loading && novels.length > 0 && shown.length === 0 && (
        <div className="empty">
          <h3>No match</h3>
          <p>Nothing here matches that search.</p>
        </div>
      )}

      <div className="shelf">
        {shown.map((n) => {
          const pct = n.chapter_count
            ? Math.round((n.translated_count / n.chapter_count) * 100)
            : 0;
          return (
            <div className="book-card" key={n.id}>
              <Link href={`/novel?id=${n.id}`}>
                <BookCover title={n.title} id={n.id} />
                <div className="body">
                  <div className="title">{n.title}</div>
                  <div className="author">{n.author || "Unknown author"}</div>
                  <div className="pill-row">
                    <span className={`pill status-${n.status}`}>{n.status}</span>
                    <span className="pill">{n.chapter_count} ch</span>
                    <span className="pill">{n.source_lang}</span>
                  </div>
                  <div className="meter" aria-hidden="true">
                    <span style={{ width: `${pct}%` }} />
                  </div>
                  <div className="meter-label">
                    <span>{pct}% translated</span>
                    <span>{compactNumber(n.char_count)} chars</span>
                  </div>
                </div>
              </Link>
            </div>
          );
        })}
      </div>
    </>
  );
}
