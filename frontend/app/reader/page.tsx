"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import {
  api,
  AskOut,
  ChapterDetail,
  ChapterRow,
  CRITIC_MAX_CHARS,
  Novel,
} from "../../lib/api";

type View = "translation" | "source" | "both";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function ReaderInner() {
  const params = useSearchParams();
  const router = useRouter();
  const novelId = Number(params.get("novel") || "0");
  const chapterIdx = Number(params.get("ch") || "0");

  const [novel, setNovel] = useState<Novel | null>(null);
  const [chapters, setChapters] = useState<ChapterRow[]>([]);
  const [chapter, setChapter] = useState<ChapterDetail | null>(null);
  const [view, setView] = useState<View>("translation");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskOut | null>(null);
  const [asking, setAsking] = useState(false);

  const loadChapter = useCallback(async () => {
    if (!novelId) return;
    setErr(null);
    try {
      const c = await api.getChapter(novelId, chapterIdx);
      setChapter(c);
      // Nothing to show in translation view until one exists.
      setView(c.translation ? "translation" : "source");
    } catch (e) {
      setErr(String(e));
      setChapter(null);
    }
  }, [novelId, chapterIdx]);

  useEffect(() => {
    if (!novelId) return;
    api.getNovel(novelId).then(setNovel).catch((e) => setErr(String(e)));
    api.listChapters(novelId).then(setChapters).catch(() => undefined);
  }, [novelId]);

  useEffect(() => {
    loadChapter();
  }, [loadChapter]);

  // Reading position doubles as the spoiler cap for questions.
  useEffect(() => {
    if (!novelId) return;
    api
      .setProgress({ novel_id: novelId, current_chapter: chapterIdx })
      .catch(() => undefined);
  }, [novelId, chapterIdx]);

  async function translateThis() {
    if (!chapter) return;
    setBusy(true);
    setErr(null);
    setProgress(null);
    try {
      if (chapter.char_count <= CRITIC_MAX_CHARS) {
        await api.translate({ novel_id: novelId, chapter_idx: chapterIdx });
      } else {
        // Long chapter: resumable, critic-free passes until complete.
        let stalls = 0;
        for (;;) {
          const r = await api.translateStep({
            novel_id: novelId,
            chapter_idx: chapterIdx,
          });
          if (r.complete) break;
          if (r.stalled) {
            stalls += 1;
            if (stalls > 8) {
              throw new Error(
                "Gemini kept returning nothing — likely the free daily quota. " +
                  "Progress is saved; resume this later.",
              );
            }
            setProgress("Rate-limited, waiting...");
            await sleep(20000);
          } else {
            stalls = 0;
            setProgress(`Piece ${r.pieces_done}/${r.pieces_total}...`);
            await sleep(4000); // pace under the 15 req/min free tier
          }
        }
      }
      await loadChapter();
      setView("translation");
      api.listChapters(novelId).then(setChapters).catch(() => undefined);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function ask() {
    if (!question.trim()) return;
    setAsking(true);
    setAnswer(null);
    setErr(null);
    try {
      const res = await api.ask({
        novel_id: novelId,
        question: question.trim(),
        current_chapter: chapterIdx,
      });
      setAnswer(res);
    } catch (e) {
      setErr(String(e));
    } finally {
      setAsking(false);
    }
  }

  function go(idx: number) {
    router.push(`/reader?novel=${novelId}&ch=${idx}`);
  }

  if (!novelId) {
    return (
      <div className="empty">
        <h3>No book chosen</h3>
        <p>
          Pick one from <Link href="/">the library</Link>.
        </p>
      </div>
    );
  }

  const last = chapters.length ? chapters[chapters.length - 1].idx : chapterIdx;
  const hasPrev = chapterIdx > 0;
  const hasNext = chapterIdx < last;
  const heading =
    chapter?.title || `Chapter ${chapterIdx + 1}`;

  return (
    <>
      <div className="page-head" style={{ marginBottom: 10 }}>
        <div className="small muted">
          <Link href="/">Library</Link>
          {novel && (
            <>
              {" / "}
              <Link href={`/novel?id=${novel.id}`}>{novel.title}</Link>
            </>
          )}
          {" / "}
          {heading}
        </div>
      </div>

      {err && <div className="error">{err}</div>}

      <div className="reader-bar">
        <div className="row">
          <button
            className="secondary"
            onClick={() => go(chapterIdx - 1)}
            disabled={!hasPrev}
          >
            Previous
          </button>
          <span className="small muted">
            {chapterIdx + 1}
            {chapters.length ? ` of ${chapters.length}` : ""}
          </span>
          <button
            className="secondary"
            onClick={() => go(chapterIdx + 1)}
            disabled={!hasNext}
          >
            Next
          </button>
        </div>
        <div className="row">
          <div className="seg">
            <button
              className={view === "translation" ? "on" : ""}
              onClick={() => setView("translation")}
              disabled={!chapter?.translation}
            >
              Translation
            </button>
            <button
              className={view === "source" ? "on" : ""}
              onClick={() => setView("source")}
            >
              Source
            </button>
            <button
              className={view === "both" ? "on" : ""}
              onClick={() => setView("both")}
              disabled={!chapter?.translation}
            >
              Both
            </button>
          </div>
          {chapter && !chapter.complete && (
            <button onClick={translateThis} disabled={busy}>
              {busy
                ? progress || "Translating..."
                : chapter.pieces_done != null
                  ? `Resume translation (${chapter.pieces_done} done)`
                  : "Translate this chapter"}
            </button>
          )}
        </div>
      </div>

      <div className="reader-pane">
        <div className="panel">
          <h2 style={{ marginTop: 0, fontSize: 19 }}>{heading}</h2>
          {!chapter && <p className="muted">Loading...</p>}

          {chapter && view === "both" && chapter.translation && (
            <div className="grid-2">
              <div>
                <div className="small muted">Source</div>
                <div className="prose source">{chapter.source_text}</div>
              </div>
              <div>
                <div className="small muted">English</div>
                <div className="prose">{chapter.translation}</div>
              </div>
            </div>
          )}

          {chapter && view === "translation" && chapter.translation && (
            <div className="prose">{chapter.translation}</div>
          )}

          {chapter && view === "source" && (
            <div className="prose source">{chapter.source_text}</div>
          )}

          {chapter && chapter.translated_with && view !== "source" && (
            <p className="small muted" style={{ marginTop: 18 }}>
              {chapter.complete ? (
                <>
                  Translated with {chapter.translated_with}
                  {chapter.critic_passes
                    ? `, ${chapter.critic_passes} critic pass${
                        chapter.critic_passes === 1 ? "" : "es"
                      }`
                    : ""}
                  . Saved, so reopening it costs nothing.
                </>
              ) : (
                <>
                  Partial translation
                  {chapter.pieces_done != null
                    ? ` — ${chapter.pieces_done} piece${
                        chapter.pieces_done === 1 ? "" : "s"
                      } done`
                    : ""}
                  . Press “Resume translation” above to finish it.
                </>
              )}
            </p>
          )}
        </div>

        <div>
          <div className="panel">
            <h3 style={{ marginTop: 0, fontSize: 15 }}>Ask about this book</h3>
            <p className="small muted">
              Answers only use chapters up to this one, so nothing ahead is
              spoiled.
            </p>
            <textarea
              style={{ minHeight: 70, fontFamily: "inherit" }}
              placeholder="Who is the woman from the first chapter?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button onClick={ask} disabled={asking} style={{ marginTop: 8 }}>
              {asking ? "Thinking..." : "Ask"}
            </button>
            {answer && (
              <>
                <p style={{ marginBottom: 6 }}>{answer.answer}</p>
                {answer.citations.length > 0 && (
                  <details>
                    <summary className="small muted">
                      {answer.citations.length} citation
                      {answer.citations.length === 1 ? "" : "s"}
                    </summary>
                    {answer.citations.map((c, i) => (
                      <p key={i} className="small muted">
                        Chapter {c.chapter_idx + 1}: {c.text.slice(0, 160)}
                      </p>
                    ))}
                  </details>
                )}
              </>
            )}
          </div>

          {novel && (
            <div className="panel">
              <h3 style={{ marginTop: 0, fontSize: 15 }}>Quick links</h3>
              <p className="small">
                <Link href={`/glossary?novel=${novel.id}&up_to=${chapterIdx}`}>
                  Glossary up to here
                </Link>
              </p>
              <p className="small">
                <Link href={`/kg?novel=${novel.id}&up_to=${chapterIdx}`}>
                  Knowledge graph up to here
                </Link>
              </p>
              <p className="small">
                <Link href={`/novel?id=${novel.id}`}>All chapters</Link>
              </p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default function ReaderPage() {
  return (
    <Suspense fallback={<p className="muted">Loading...</p>}>
      <ReaderInner />
    </Suspense>
  );
}
