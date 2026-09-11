"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, KgEdge, KgNode, KgOut } from "../../lib/api";

interface Pos {
  x: number;
  y: number;
}

// Minimal force layout — keeps frontend dep count at zero beyond Next + React.
function layout(nodes: KgNode[], edges: KgEdge[], w: number, h: number, iters = 200): Map<string, Pos> {
  const positions = new Map<string, Pos>();
  // Deterministic seed by id hash
  for (const n of nodes) {
    let s = 0;
    for (let i = 0; i < n.id.length; i++) s = (s * 31 + n.id.charCodeAt(i)) | 0;
    const rng = (k: number) => {
      s = (s * 1103515245 + 12345 + k) | 0;
      return ((s >>> 0) % 10000) / 10000;
    };
    positions.set(n.id, { x: rng(1) * w, y: rng(2) * h });
  }
  const adj: Map<string, string[]> = new Map();
  for (const e of edges) {
    if (!adj.has(e.src)) adj.set(e.src, []);
    if (!adj.has(e.dst)) adj.set(e.dst, []);
    adj.get(e.src)!.push(e.dst);
    adj.get(e.dst)!.push(e.src);
  }
  const k = Math.sqrt((w * h) / Math.max(1, nodes.length)) * 0.7;
  for (let it = 0; it < iters; it++) {
    const t = 0.05 * (1 - it / iters);
    const disp = new Map<string, Pos>();
    for (const n of nodes) disp.set(n.id, { x: 0, y: 0 });

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = positions.get(nodes[i].id)!;
        const b = positions.get(nodes[j].id)!;
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const d2 = dx * dx + dy * dy + 0.01;
        const d = Math.sqrt(d2);
        const f = (k * k) / d;
        const ux = dx / d;
        const uy = dy / d;
        disp.get(nodes[i].id)!.x += ux * f;
        disp.get(nodes[i].id)!.y += uy * f;
        disp.get(nodes[j].id)!.x -= ux * f;
        disp.get(nodes[j].id)!.y -= uy * f;
      }
    }
    for (const e of edges) {
      const a = positions.get(e.src);
      const b = positions.get(e.dst);
      if (!a || !b) continue;
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const f = (d * d) / k;
      const ux = dx / d;
      const uy = dy / d;
      disp.get(e.src)!.x -= ux * f;
      disp.get(e.src)!.y -= uy * f;
      disp.get(e.dst)!.x += ux * f;
      disp.get(e.dst)!.y += uy * f;
    }
    for (const n of nodes) {
      const d = disp.get(n.id)!;
      const p = positions.get(n.id)!;
      const len = Math.sqrt(d.x * d.x + d.y * d.y) + 0.01;
      p.x += (d.x / len) * Math.min(len, t * 200);
      p.y += (d.y / len) * Math.min(len, t * 200);
      p.x = Math.max(20, Math.min(w - 20, p.x));
      p.y = Math.max(20, Math.min(h - 20, p.y));
    }
  }
  return positions;
}

const KIND_COLOR: Record<string, string> = {
  character: "#58a6ff",
  sect: "#f0883e",
  technique: "#a371f7",
  realm: "#3fb950",
  item: "#d29922",
  place: "#79c0ff",
  other: "#8b949e",
};

function KgInner() {
  const params = useSearchParams();
  const novelId = Number(params.get("novel") || "0");
  const upTo = Number(params.get("up_to") || "100000");
  const [data, setData] = useState<KgOut | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!novelId) return;
    api.kg(novelId, upTo).then(setData).catch((e) => setErr(String(e)));
  }, [novelId, upTo]);

  const W = 900;
  const H = 600;
  const pos = useMemo(() => {
    if (!data) return null;
    return layout(data.nodes, data.edges, W, H);
  }, [data]);

  if (!novelId) {
    return (
      <div>
        <h1>Knowledge Graph</h1>
        <p className="muted">
          Pick a novel from <Link href="/">the home page</Link>.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1>Knowledge Graph</h1>
      <p className="muted">
        Up to chapter {upTo === 100000 ? "∞" : upTo}. Nothing past your reading position is rendered.
      </p>
      {err && <div className="error">{err}</div>}
      <div className="panel" style={{ overflow: "auto" }}>
        {data && pos ? (
          <svg
            width={W}
            height={H}
            viewBox={`0 0 ${W} ${H}`}
            style={{ background: "#0d1117", borderRadius: 8, display: "block" }}
          >
            {data.edges.map((e, i) => {
              const a = pos.get(e.src);
              const b = pos.get(e.dst);
              if (!a || !b) return null;
              return (
                <g key={i}>
                  <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#30363d" strokeWidth={1} />
                  <text
                    x={(a.x + b.x) / 2}
                    y={(a.y + b.y) / 2}
                    fill="#8b949e"
                    fontSize={10}
                    textAnchor="middle"
                  >
                    {e.relation}
                  </text>
                </g>
              );
            })}
            {data.nodes.map((n) => {
              const p = pos.get(n.id)!;
              const c = KIND_COLOR[n.kind] || KIND_COLOR.other;
              return (
                <g key={n.id} transform={`translate(${p.x},${p.y})`}>
                  <circle r={9} fill={c} stroke="#161b22" strokeWidth={2} />
                  <text x={12} y={4} fill="#e6edf3" fontSize={11}>
                    {n.label}
                  </text>
                </g>
              );
            })}
          </svg>
        ) : (
          <p className="muted">Building graph...</p>
        )}
      </div>
      {data && (
        <div className="panel">
          <div className="row">
            {Object.entries(KIND_COLOR).map(([k, c]) => (
              <span key={k} className="badge" style={{ color: c, borderColor: c }}>
                {k}
              </span>
            ))}
          </div>
          <p className="muted small" style={{ marginTop: 8 }}>
            {data.nodes.length} nodes / {data.edges.length} edges
          </p>
        </div>
      )}
    </div>
  );
}

export default function KgPage() {
  return (
    <Suspense fallback={<p className="muted">Loading...</p>}>
      <KgInner />
    </Suspense>
  );
}
