"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import BookCover from "../../components/BookCover";
import { displayTitle, errorText } from "../../lib/api";
import { compact, RankedNovel, RankPeriod, siteApi } from "../../lib/api-site";

const TABS: { key: RankPeriod; label: string }[] = [
  { key: "day", label: "Today" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
  { key: "all", label: "All time" },
];

export default function RankingsPage() {
  const [period, setPeriod] = useState<RankPeriod>("week");
  const [rows, setRows] = useState<RankedNovel[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setRows(null);
    setErr(null);
    siteApi
      .rankings(period)
      .then((r) => live && setRows(r))
      .catch((e) => live && setErr(errorText(e)));
    return () => {
      live = false;
    };
  }, [period]);

  return (
    <>
      <div className="page-head">
        <h1>Rankings</h1>
      </div>
      <div className="seg" style={{ marginBottom: 18, width: "fit-content" }}>
        {TABS.map((t) => (
          <button key={t.key} className={period === t.key ? "on" : ""} onClick={() => setPeriod(t.key)}>
            {t.label}
          </button>
        ))}
      </div>
      {err && <div className="error">{err}</div>}
      {!rows && !err && <p className="muted">Loading...</p>}
      {rows && rows.length === 0 && (
        <div className="empty">
          <h3>No readers yet</h3>
          <p>Nothing has been read in this period.</p>
        </div>
      )}
      <ol className="rank-list">
        {rows?.map((n) => {
          const t = displayTitle(n.title, n.title_en);
          return (
            <li key={n.id} className="rank-item">
              <span className="rank-num">{n.rank}</span>
              <Link href={`/novel?id=${n.id}`} className="rank-link">
                <BookCover title={t.text} id={n.id} size="sm" hasCover={Boolean(n.has_cover)} coverVersion={n.cover_version} />
                <div className="rank-body">
                  <div className="title" title={t.hover}>{t.text}</div>
                  <div className="author">{n.author || "Unknown author"}</div>
                  <div className="pill-row">
                    <span className="pill">{compact(n.views)} views</span>
                    <span className="pill">
                      {n.rating_avg != null
                        ? `★ ${n.rating_avg.toFixed(1)} (${n.rating_count ?? 0})`
                        : "No ratings"}
                    </span>
                  </div>
                </div>
              </Link>
            </li>
          );
        })}
      </ol>
    </>
  );
}
