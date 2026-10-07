"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import BookCover from "../components/BookCover";
import { IconArrowUpDown, IconChevronDown, IconSearch, IconSlidersHorizontal, IconUpload, IconX } from "../components/icons";
import { api, errorText, Novel, NovelQuery } from "../lib/api";

const PAGE_SIZE = 24;

// Length buckets map to the API's min/max chapter filters.
const LENGTHS: Record<string, { label: string; min?: number; max?: number }> = {
  "": { label: "Any length" },
  short: { label: "<100", max: 99 },
  medium: { label: "100–500", min: 100, max: 499 },
  long: { label: "500–1000", min: 500, max: 999 },
  epic: { label: "1000+", min: 1000 },
};

const SORTS = ["updated", "new", "chapters"] as const;
type SortKey = (typeof SORTS)[number];

function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

function CatalogInner() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const q = params.get("q") || "";
  const tag = params.get("tag") || "";
  const status = params.get("status") || "";
  const length = LENGTHS[params.get("length") || ""] ? params.get("length") || "" : "";
  const sortParam = params.get("sort") as SortKey | null;
  const sort: SortKey = sortParam && SORTS.includes(sortParam) ? sortParam : "updated";

  // The search box is typed into freely and committed to the URL on a pause.
  const [qDraft, setQDraft] = useState(q);
  const [tagDraft, setTagDraft] = useState(tag);
  useEffect(() => setQDraft(q), [q]);
  useEffect(() => setTagDraft(tag), [tag]);

  const [novels, setNovels] = useState<Novel[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const reqId = useRef(0);

  const setParam = useCallback(
    (changes: Record<string, string>) => {
      const sp = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(changes)) {
        if (v) sp.set(k, v);
        else sp.delete(k);
      }
      const qs = sp.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [params, router, pathname],
  );

  // Debounce the free-text fields into the URL.
  useEffect(() => {
    if (qDraft.trim() === q && tagDraft.trim() === tag) return;
    const t = setTimeout(
      () => setParam({ q: qDraft.trim(), tag: tagDraft.trim() }),
      350,
    );
    return () => clearTimeout(t);
  }, [qDraft, tagDraft, q, tag, setParam]);

  const buildQuery = useCallback(
    (offset: number): NovelQuery => {
      const len = LENGTHS[length];
      return {
        q: q || undefined,
        tag: tag || undefined,
        status: status || undefined,
        min_chapters: len.min,
        max_chapters: len.max,
        sort,
        limit: PAGE_SIZE,
        offset,
      };
    },
    [q, tag, status, length, sort],
  );

  useEffect(() => {
    const id = ++reqId.current;
    setLoading(true);
    setErr(null);
    api
      .listNovels(buildQuery(0))
      .then((rows) => {
        if (id !== reqId.current) return;
        setNovels(rows);
        setHasMore(rows.length === PAGE_SIZE);
      })
      .catch((e) => {
        if (id === reqId.current) setErr(errorText(e));
      })
      .finally(() => {
        if (id === reqId.current) setLoading(false);
      });
  }, [buildQuery]);

  async function loadMore() {
    const id = reqId.current;
    setLoadingMore(true);
    try {
      const rows = await api.listNovels(buildQuery(novels.length));
      if (id !== reqId.current) return;
      setNovels((prev) => [...prev, ...rows]);
      setHasMore(rows.length === PAGE_SIZE);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setLoadingMore(false);
    }
  }

  const filtered = Boolean(q || tag || status || length);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Novels</h1>
          <div className="sub">
            {loading
              ? "Loading..."
              : `${novels.length}${hasMore ? "+" : ""} novel${novels.length === 1 ? "" : "s"}${
                  filtered ? " match" : ""
                }`}
          </div>
        </div>
        <Link href="/import">
          <button><IconUpload /> <span>Import a book</span></button>
        </Link>
      </div>

      {err && <div className="error">{err}</div>}

      <div className="toolbar">
        <IconSearch />
        <input
          className="grow"
          type="search"
          placeholder="Search title or author"
          value={qDraft}
          onChange={(e) => setQDraft(e.target.value)}
        />
        <input
          type="text"
          placeholder="Tag"
          value={tagDraft}
          onChange={(e) => setTagDraft(e.target.value)}
          aria-label="Tag"
          style={{ width: 120 }}
        />
        <IconSlidersHorizontal />
        <select
          value={status}
          onChange={(e) => setParam({ status: e.target.value })}
          aria-label="Status"
        >
          <option value="">Any status</option>
          <option value="ongoing">Ongoing</option>
          <option value="completed">Completed</option>
          <option value="hiatus">Hiatus</option>
        </select>
        <select
          value={length}
          onChange={(e) => setParam({ length: e.target.value })}
          aria-label="Length"
        >
          {Object.entries(LENGTHS).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </select>
        <IconArrowUpDown />
        <select
          value={sort}
          onChange={(e) =>
            setParam({ sort: e.target.value === "updated" ? "" : e.target.value })
          }
          aria-label="Sort"
        >
          <option value="updated">Recently updated</option>
          <option value="new">Newest</option>
          <option value="chapters">Most chapters</option>
        </select>
        {filtered && (
          <button
            className="secondary"
            onClick={() => router.replace(pathname)}
          >
            <IconX /> <span>Clear</span>
          </button>
        )}
      </div>

      {!loading && novels.length === 0 && !err && (
        <div className="empty">
          {filtered ? (
            <>
              <h3>No match</h3>
              <p>Nothing here matches those filters.</p>
            </>
          ) : (
            <>
              <h3>Nothing on the shelf yet</h3>
              <p>
                Import a .txt, .epub or .pdf file, paste a chapter, or pull one
                from a URL.
              </p>
              <Link href="/import">
                <button><IconUpload /> <span>Import your first book</span></button>
              </Link>
            </>
          )}
        </div>
      )}

      <div className="shelf">
        {novels.map((n) => {
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

      {hasMore && !loading && (
        <div className="row" style={{ justifyContent: "center", marginTop: 20 }}>
          <button className="secondary" onClick={loadMore} disabled={loadingMore}>
            {loadingMore ? "Loading..." : <><IconChevronDown /> <span>Load more</span></>}
          </button>
        </div>
      )}
    </>
  );
}

export default function LibraryPage() {
  return (
    <Suspense fallback={<p className="muted">Loading...</p>}>
      <CatalogInner />
    </Suspense>
  );
}
