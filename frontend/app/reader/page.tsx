"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, AskOut, Citation, Novel, TranslateResult } from "../../lib/api";

function ReaderInner() {
  const params = useSearchParams();
  const novelId = Number(params.get("novel") || "0");

  const [novels, setNovels] = useState<Novel[]>([]);
  const [chapterIdx, setChapterIdx] = useState<number>(0);
  const [targetLang, setTargetLang] = useState("en");
  const [translation, setTranslation] = useState<TranslateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [question, setQuestion] = useState("");
  const [currentChapter, setCurrentChapter] = useState(0);
  const [answer, setAnswer] = useState<AskOut | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    api.listNovels().then(setNovels).catch((e) => setErr(String(e)));
  }, []);

  const novel = novels.find((n) => n.id === novelId);

  async function onTranslate() {
    if (!novelId) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.translate({
        novel_id: novelId,
        chapter_idx: chapterIdx,
        target_lang: targetLang,
      });
      setTranslation(r);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onAsk() {
    if (!novelId || !question.trim()) return;
    setAsking(true);
    setErr(null);
    try {
      const r = await api.ask({
        novel_id: novelId,
        question,
        current_chapter: currentChapter,
        answer_lang: targetLang,
      });
      setAnswer(r);
    } catch (e) {
      setErr(String(e));
    } finally {
      setAsking(false);
    }
  }

  async function onSetProgress() {
    if (!novelId) return;
    try {
      await api.setProgress({ novel_id: novelId, current_chapter: currentChapter });
    } catch (e) {
      setErr(String(e));
    }
  }

  if (!novelId) {
    return (
      <div>
        <h1>Reader</h1>
        <p className="muted">
          Pick a novel from <Link href="/">the home page</Link>.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1>Reader</h1>
      <p className="muted">
        {novel ? `${novel.title} (${novel.chapter_count} chapters)` : "Loading..."}
      </p>
      {err && <div className="error">{err}</div>}

      <div className="reader-pane">
        <div>
          <div className="panel">
            <div className="row">
              <label className="small muted">Chapter</label>
              <input
                type="number"
                min={0}
                value={chapterIdx}
                onChange={(e) => setChapterIdx(Number(e.target.value))}
                style={{ width: 90 }}
              />
              <label className="small muted">Target</label>
              <select value={targetLang} onChange={(e) => setTargetLang(e.target.value)}>
                <option value="en">English</option>
                <option value="ja">Japanese</option>
                <option value="ko">Korean</option>
              </select>
              <button disabled={busy} onClick={onTranslate}>
                {busy ? "Translating..." : "Translate chapter"}
              </button>
            </div>
            {translation && (
              <div style={{ marginTop: 16 }}>
                <div className="row small muted" style={{ marginBottom: 8 }}>
                  <span className="badge">ch {translation.chapter_idx}</span>
                  <span className="badge">+{translation.new_terms} new terms</span>
                  <span className="badge">{translation.critic_passes} critic passes</span>
                </div>
                <div className="chap-body">{translation.translation}</div>
              </div>
            )}
          </div>

          <div className="panel">
            <h3>Ask the novel</h3>
            <div className="col">
              <input
                type="text"
                placeholder="e.g. Who is Wang Lin's master?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
              <div className="row">
                <label className="small muted">Current chapter (spoiler cap)</label>
                <input
                  type="number"
                  min={0}
                  value={currentChapter}
                  onChange={(e) => setCurrentChapter(Number(e.target.value))}
                  style={{ width: 90 }}
                />
                <button className="secondary" onClick={onSetProgress}>
                  Save progress
                </button>
                <button disabled={asking} onClick={onAsk}>
                  {asking ? "Thinking..." : "Ask"}
                </button>
              </div>
              {answer && <AnswerView a={answer} />}
            </div>
          </div>
        </div>

        <aside>
          <div className="panel">
            <h3>Spoiler control</h3>
            <p className="small muted">
              The Q&A agent only sees chunks from chapter ≤ <b>{currentChapter}</b>.
              Future chapters never reach the model.
            </p>
            <p className="small muted">
              Eval target: <span className="badge good">0% leakage</span>
            </p>
          </div>
          <div className="panel">
            <h3>Quick links</h3>
            <p className="small">
              <a href={`/glossary?novel=${novelId}&up_to=${currentChapter}`}>Glossary up to ch {currentChapter}</a>
            </p>
            <p className="small">
              <a href={`/kg?novel=${novelId}&up_to=${currentChapter}`}>Knowledge graph up to ch {currentChapter}</a>
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

function AnswerView({ a }: { a: AskOut }) {
  return (
    <div>
      <div className="chap-body" style={{ marginTop: 12 }}>{a.answer}</div>
      {a.citations.length > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary className="muted small">
            {a.citations.length} citations
          </summary>
          <ul>
            {a.citations.map((c: Citation, i: number) => (
              <li key={i} className="small">
                <b>ch {c.chapter_idx}</b> (score {c.score.toFixed(3)}):{" "}
                <span className="muted">{c.text.slice(0, 240)}...</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function ReaderPage() {
  return (
    <Suspense fallback={<p className="muted">Loading...</p>}>
      <ReaderInner />
    </Suspense>
  );
}
