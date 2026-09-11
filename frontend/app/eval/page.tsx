"use client";

// Eval dashboard reads from the backend by hitting /static-served report file.
// For dev, we fetch latest.json over HTTP if exposed; otherwise the user just
// runs `python -m eval.run all` and refreshes.

import { useEffect, useState } from "react";

interface QASummary {
  n: number;
  n_normal: number;
  n_spoiler: number;
  accuracy: number;
  spoiler_leakage: number;
  citation_accuracy: number;
  targets: { accuracy: number; spoiler_leakage: number };
  rows?: unknown[];
}

interface TermSummary {
  n_terms_observed: number;
  term_consistency: number;
}

interface TranslateSummary {
  novel: string;
  chapters_sampled: number;
  beyonder: TermSummary;
  deepl: TermSummary | { skipped: string };
  targets: { term_consistency: number };
}

interface Report {
  timestamp: string;
  model: string;
  qa?: QASummary | { skipped: string };
  translate?: TranslateSummary | { skipped: string };
}

const REPORT_URL = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/eval/latest`;

export default function EvalPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch(REPORT_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setReport)
      .catch((e) => setErr(`No report yet. Run: \`python -m eval.run all\` (${e})`));
  }, []);

  return (
    <div>
      <h1>Eval dashboard</h1>
      <p className="muted">
        Run <span className="kbd">python -m eval.run all</span> to refresh metrics.
      </p>
      {err && <div className="error">{err}</div>}
      {report && (
        <>
          <div className="panel">
            <div className="row">
              <span className="badge">{report.model}</span>
              <span className="muted small">{report.timestamp}</span>
            </div>
          </div>

          {report.qa && "n" in report.qa && (
            <QABlock qa={report.qa as QASummary} />
          )}
          {report.translate && "novel" in report.translate && (
            <TranslateBlock t={report.translate as TranslateSummary} />
          )}
        </>
      )}
    </div>
  );
}

function metricCls(v: number, target: number, lowerIsBetter = false): "good" | "bad" {
  if (lowerIsBetter) return v <= target ? "good" : "bad";
  return v >= target ? "good" : "bad";
}

function QABlock({ qa }: { qa: QASummary }) {
  return (
    <div className="panel">
      <h3>Q&A</h3>
      <div className="row">
        <div className="metric">
          <span className="v">{(qa.accuracy * 100).toFixed(1)}%</span>
          <span className="l">Accuracy ({qa.n_normal} non-spoiler rows)</span>
          <span className={`badge ${metricCls(qa.accuracy, qa.targets.accuracy)}`}>
            target ≥ {(qa.targets.accuracy * 100).toFixed(0)}%
          </span>
        </div>
        <div className="metric">
          <span className="v">{(qa.spoiler_leakage * 100).toFixed(1)}%</span>
          <span className="l">Spoiler leakage ({qa.n_spoiler} probes)</span>
          <span className={`badge ${metricCls(qa.spoiler_leakage, qa.targets.spoiler_leakage, true)}`}>
            target ≤ {(qa.targets.spoiler_leakage * 100).toFixed(0)}%
          </span>
        </div>
        <div className="metric">
          <span className="v">{(qa.citation_accuracy * 100).toFixed(1)}%</span>
          <span className="l">Citation accuracy</span>
        </div>
      </div>
    </div>
  );
}

function TranslateBlock({ t }: { t: TranslateSummary }) {
  const by = t.beyonder.term_consistency;
  const dl =
    "term_consistency" in t.deepl ? t.deepl.term_consistency : null;
  return (
    <div className="panel">
      <h3>Translation</h3>
      <p className="muted small">
        Novel: <b>{t.novel}</b> · {t.chapters_sampled} chapters sampled
      </p>
      <div className="row">
        <div className="metric">
          <span className="v">{(by * 100).toFixed(1)}%</span>
          <span className="l">Beyonder term consistency</span>
          <span className={`badge ${metricCls(by, t.targets.term_consistency)}`}>
            target ≥ {(t.targets.term_consistency * 100).toFixed(0)}%
          </span>
        </div>
        <div className="metric">
          <span className="v">{dl !== null ? `${(dl * 100).toFixed(1)}%` : "—"}</span>
          <span className="l">DeepL baseline</span>
          {dl !== null && (
            <span className={`badge ${by > dl ? "good" : "bad"}`}>
              {by > dl ? "winning" : "losing"} by {((by - dl) * 100).toFixed(1)} pts
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
