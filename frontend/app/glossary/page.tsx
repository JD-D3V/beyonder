"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, GlossaryEntry } from "../../lib/api";

function GlossaryInner() {
  const params = useSearchParams();
  const novelId = Number(params.get("novel") || "0");
  const upTo = Number(params.get("up_to") || "100000");
  const [entries, setEntries] = useState<GlossaryEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [kind, setKind] = useState<string>("all");

  useEffect(() => {
    if (!novelId) return;
    api.glossary(novelId, upTo).then(setEntries).catch((e) => setErr(String(e)));
  }, [novelId, upTo]);

  if (!novelId) {
    return (
      <div>
        <h1>Glossary</h1>
        <p className="muted">
          Pick a novel from <Link href="/">the home page</Link>.
        </p>
      </div>
    );
  }

  const filtered = entries.filter(
    (e) =>
      (kind === "all" || e.kind === kind) &&
      (filter.length === 0 ||
        e.source_term.includes(filter) ||
        e.target_term.toLowerCase().includes(filter.toLowerCase()))
  );

  const counts: Record<string, number> = {};
  for (const e of entries) counts[e.kind] = (counts[e.kind] || 0) + 1;

  return (
    <div>
      <h1>Glossary</h1>
      {err && <div className="error">{err}</div>}
      <div className="panel">
        <div className="row">
          <input
            type="text"
            placeholder="filter source or target"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ maxWidth: 260 }}
          />
          <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ maxWidth: 180 }}>
            <option value="all">all kinds ({entries.length})</option>
            {Object.entries(counts).map(([k, n]) => (
              <option key={k} value={k}>
                {k} ({n})
              </option>
            ))}
          </select>
          <span className="muted small">
            Showing terms up to chapter <b>{upTo === 100000 ? "∞" : upTo}</b>
          </span>
        </div>
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>Target</th>
              <th>Kind</th>
              <th>First ch.</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e, i) => (
              <tr key={i}>
                <td><b>{e.source_term}</b></td>
                <td>{e.target_term}</td>
                <td><span className="badge">{e.kind}</span></td>
                <td>{e.first_chapter}</td>
                <td>{e.confidence.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && <p className="muted">No terms match.</p>}
      </div>
    </div>
  );
}

export default function GlossaryPage() {
  return (
    <Suspense fallback={<p className="muted">Loading...</p>}>
      <GlossaryInner />
    </Suspense>
  );
}
