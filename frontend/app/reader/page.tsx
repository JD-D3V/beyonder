"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  type CSSProperties,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import GlossaryText from "../../components/GlossaryText";
import {
  IconBookmark,
  IconBookmarkCheck,
  IconChevronLeft,
  IconChevronRight,
  IconFlag,
  IconLoaderCircle,
  IconMessageCircleQuestionMark,
  IconSettings,
  IconSparkles,
  IconType,
} from "../../components/icons";
import ReaderSettings from "../../components/ReaderSettings";
import {
  api,
  ApiError,
  AskOut,
  ChapterDetail,
  ChapterRow,
  CRITIC_MAX_CHARS,
  GlossaryEntry,
  KeyRequiredError,
  Novel,
} from "../../lib/api";
import { getSession, SESSION_EVENT, type Session } from "../../lib/session";
import {
  DEFAULT_PREFS,
  loadPrefs,
  ReaderPrefs,
  savePrefs,
} from "../../lib/readerPrefs";

type View = "translation" | "source" | "both";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Layout effects warn when rendered on the server; the static export
// prerenders this page, so only use one in the browser.
const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

function isTyping(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el || !el.tagName) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable
  );
}

function ReaderInner() {
  const params = useSearchParams();
  const router = useRouter();
  const novelId = Number(params.get("novel") || "0");
  const chapterIdx = Number(params.get("ch") || "0");

  const [session, setSession] = useState<Session | null>(null);
  const [prefs, setPrefs] = useState<ReaderPrefs>(DEFAULT_PREFS);
  const [showSettings, setShowSettings] = useState(false);

  const [novel, setNovel] = useState<Novel | null>(null);
  const [chapters, setChapters] = useState<ChapterRow[]>([]);
  const [chapter, setChapter] = useState<ChapterDetail | null>(null);
  const [glossary, setGlossary] = useState<GlossaryEntry[]>([]);
  const [flagCount, setFlagCount] = useState(0);
  const [onReading, setOnReading] = useState(false);
  const [view, setView] = useState<View>("translation");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [newTerms, setNewTerms] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [keyNeeded, setKeyNeeded] = useState(false);
  const [keyRejected, setKeyRejected] = useState(false);

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskOut | null>(null);
  const [asking, setAsking] = useState(false);
  const [askErr, setAskErr] = useState<string | null>(null);
  const [askKeyNeeded, setAskKeyNeeded] = useState(false);

  const signedIn = session !== null;

  // Prefs come from localStorage, which the prerendered HTML cannot know.
  // Reading them in a layout effect applies them before the first paint, so
  // there is no flash of the wrong theme and no hydration mismatch (the
  // server and first client render both use DEFAULT_PREFS).
  useIsoLayoutEffect(() => {
    setPrefs(loadPrefs());
  }, []);

  useEffect(() => {
    const sync = () => setSession(getSession());
    sync();
    window.addEventListener(SESSION_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(SESSION_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  function changePrefs(next: ReaderPrefs) {
    setPrefs(next);
    savePrefs(next);
  }

  // Bumped whenever the chapter changes or the page unmounts; a running
  // translate loop holds the token it started with and stops when stale.
  const runToken = useRef(0);

  const loadChapter = useCallback(
    async (isCurrent: () => boolean = () => true) => {
      if (!novelId) return;
      try {
        // For signed-in readers this also advances server-side progress.
        const c = await api.getChapter(novelId, chapterIdx);
        if (!isCurrent()) return;
        setChapter(c);
        // Nothing to show in translation view until one exists.
        setView(c.translation ? "translation" : "source");
        return c;
      } catch (e) {
        if (!isCurrent()) return;
        setErr(String(e));
        setChapter(null);
      }
    },
    [novelId, chapterIdx],
  );

  useEffect(() => {
    if (!novelId) return;
    api.getNovel(novelId).then(setNovel).catch((e) => setErr(String(e)));
    api.listChapters(novelId).then(setChapters).catch(() => undefined);
  }, [novelId]);

  useEffect(() => {
    const token = ++runToken.current;
    // Per-chapter transient state starts clean; a stale loop is cancelled.
    setNewTerms(null);
    setAnswer(null);
    setAskErr(null);
    setAskKeyNeeded(false);
    setKeyNeeded(false);
    setKeyRejected(false);
    setErr(null);
    setBusy(false);
    setProgress(null);
    loadChapter(() => runToken.current === token);
    return () => {
      // Chapter change or unmount: invalidate any in-flight run.
      if (runToken.current === token) runToken.current += 1;
    };
  }, [loadChapter]);

  // Signed-out readers keep their place in this browser.
  useEffect(() => {
    if (!novelId) return;
    try {
      const key = "beyonder.anonProgress";
      const cur = JSON.parse(window.localStorage.getItem(key) || "{}");
      cur[String(novelId)] = chapterIdx;
      window.localStorage.setItem(key, JSON.stringify(cur));
    } catch {
      // storage blocked; nothing to do
    }
  }, [novelId, chapterIdx]);

  const loadGlossary = useCallback(() => {
    if (!novelId) return;
    api.glossary(novelId).then(setGlossary).catch(() => setGlossary([]));
  }, [novelId]);

  useEffect(() => {
    loadGlossary();
  }, [loadGlossary, signedIn]);

  useEffect(() => {
    if (!novelId) return;
    api
      .flags(novelId, "open", undefined, chapterIdx)
      .then((f) => setFlagCount(f.length))
      .catch(() => setFlagCount(0));
  }, [novelId, chapterIdx, signedIn]);

  useEffect(() => {
    if (!novelId || !signedIn) {
      setOnReading(false);
      return;
    }
    api
      .library()
      .then((lib) => setOnReading(lib.reading.some((n) => n.id === novelId)))
      .catch(() => undefined);
  }, [novelId, signedIn]);

  async function toggleReading() {
    try {
      if (onReading) await api.removeFromLibrary(novelId);
      else await api.setShelf(novelId, "reading");
      setOnReading(!onReading);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function translateThis() {
    if (!chapter) return;
    const token = runToken.current;
    const live = () => runToken.current === token;
    setBusy(true);
    setErr(null);
    setKeyNeeded(false);
    setKeyRejected(false);
    setProgress(null);
    let added = 0;
    let reload = false;
    try {
      if (chapter.char_count <= CRITIC_MAX_CHARS) {
        const r = await api.translate({ novel_id: novelId, chapter_idx: chapterIdx });
        added += r.new_terms?.length ?? 0;
      } else {
        // Long chapter: resumable, critic-free passes until complete.
        let stalls = 0;
        for (;;) {
          if (!live()) return;
          const r = await api.translateStep({
            novel_id: novelId,
            chapter_idx: chapterIdx,
          });
          if (!live()) return;
          added += r.new_terms?.length ?? 0;
          if (r.complete) break;
          if (r.stalled) {
            stalls += 1;
            if (stalls > 8) {
              throw new Error(
                "The AI provider kept returning nothing, likely a quota limit. " +
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
          if (!live()) return;
        }
      }
      reload = true;
      if (live()) setNewTerms(added);
    } catch (e) {
      if (!live()) return;
      if (e instanceof KeyRequiredError) setKeyNeeded(true);
      else if (e instanceof ApiError && e.code === "already_translated") reload = true;
      else if (e instanceof ApiError && e.code === "llm_rate_limited")
        setErr("The AI provider is rate-limiting your key, try again in a minute.");
      else if (e instanceof ApiError && e.code === "llm_key_invalid") setKeyRejected(true);
      else setErr(e instanceof Error ? e.message : String(e));
    }
    if (!live()) return;
    if (reload) {
      await loadChapter(live);
      if (!live()) return;
      loadGlossary();
      api.listChapters(novelId).then((c) => live() && setChapters(c)).catch(() => undefined);
    }
    setBusy(false);
    setProgress(null);
  }

  async function ask() {
    if (!question.trim()) return;
    setAsking(true);
    setAnswer(null);
    setAskErr(null);
    setAskKeyNeeded(false);
    try {
      // The server caps answers at the stored reading progress.
      const res = await api.ask({ novel_id: novelId, question: question.trim() });
      setAnswer(res);
    } catch (e) {
      if (e instanceof KeyRequiredError) setAskKeyNeeded(true);
      else setAskErr(String(e));
    } finally {
      setAsking(false);
    }
  }

  const last = chapters.length ? chapters[chapters.length - 1].idx : chapterIdx;
  const hasPrev = chapterIdx > 0;
  const hasNext = chapterIdx < last;

  const go = useCallback(
    (idx: number) => {
      router.push(`/reader?novel=${novelId}&ch=${idx}`);
      window.scrollTo({ top: 0 });
    },
    [router, novelId],
  );

  // Keep the key handler's view of position fresh without re-binding.
  const nav = useRef({ hasPrev, hasNext, chapterIdx, go });
  nav.current = { hasPrev, hasNext, chapterIdx, go };

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (isTyping(e.target)) return;
      const n = nav.current;
      if (e.key === "ArrowLeft" && n.hasPrev) n.go(n.chapterIdx - 1);
      else if (e.key === "ArrowRight" && n.hasNext) n.go(n.chapterIdx + 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!novelId) {
    return (
      <div className="empty">
        <h3>No book chosen</h3>
        <p>
          Pick one from <Link href="/">the catalog</Link>.
        </p>
      </div>
    );
  }

  const heading = chapter?.title || `Chapter ${chapterIdx + 1}`;
  const cssVars = {
    "--r-font":
      prefs.font === "serif"
        ? 'Georgia, "Iowan Old Style", "Times New Roman", serif'
        : 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    "--r-size": `${prefs.size}px`,
    "--r-lh": String(prefs.lineHeight),
    "--r-width": `${prefs.width}px`,
  } as CSSProperties;

  const translateLabel = busy
    ? progress || "Translating..."
    : chapter?.pieces_done != null
      ? `Resume translation (${chapter.pieces_done} done)`
      : "Translate this chapter";

  const navButtons = (
    <div className="reader-nav">
      <button
        className="secondary"
        onClick={() => go(chapterIdx - 1)}
        disabled={!hasPrev}
      >
        <IconChevronLeft size={16} /> Previous
      </button>
      <span className="small">
        {chapterIdx + 1}
        {chapters.length ? ` of ${chapters.length}` : ""}
      </span>
      <button
        className="secondary"
        onClick={() => go(chapterIdx + 1)}
        disabled={!hasNext}
      >
        Next <IconChevronRight size={16} />
      </button>
    </div>
  );

  return (
    <div className="reader-root" data-theme={prefs.theme} style={cssVars}>
      <div className="reader-top">
        <div className="small reader-crumbs">
          <Link href="/library">Library</Link>
          {novel && (
            <>
              {" / "}
              <Link href={`/novel?id=${novel.id}`}>{novel.title}</Link>
            </>
          )}
          {" / "}
          {heading}
        </div>
        <div className="row" style={{ gap: 8 }}>
          {flagCount > 0 && novel && (
            <Link
              className="flag-marker"
              href={`/novel?id=${novel.id}&tab=flags`}
              title="Open review flags on this chapter"
            >
              <IconFlag size={14} /> {flagCount}
            </Link>
          )}
          {signedIn && (
            <button
              className="secondary icon-btn"
              onClick={toggleReading}
              aria-label={onReading ? "Remove from Reading shelf" : "Add to Reading shelf"}
              title={onReading ? "On your Reading shelf" : "Add to Reading shelf"}
            >
              {onReading ? <IconBookmarkCheck size={16} /> : <IconBookmark size={16} />}
            </button>
          )}
          <button
            className="secondary icon-btn"
            onClick={() => setShowSettings((v) => !v)}
            aria-label="Reader settings"
            aria-expanded={showSettings}
            title="Reader settings"
          >
            <IconType size={16} />
          </button>
        </div>
      </div>

      {showSettings && (
        <ReaderSettings
          prefs={prefs}
          onChange={changePrefs}
          onClose={() => setShowSettings(false)}
        />
      )}

      {err && <div className="error">{err}</div>}
      {keyRejected && (
        <div className="error">
          Your API key was rejected — check <Link href="/settings">Settings</Link>.
        </div>
      )}
      {keyNeeded && (
        <div className="error">
          Translation needs an AI key. <Link href="/settings">Add your API key</Link>
        </div>
      )}

      <div className="reader-controls">
        {navButtons}
        <div className="row" style={{ gap: 8 }}>
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
        </div>
      </div>

      <article className="reader-page">
        <h2 className="reader-title">{heading}</h2>
        {!chapter && !err && <p className="muted">Loading...</p>}

        {chapter && !chapter.complete && (
          <div className="translate-box">
            {signedIn ? (
              <button onClick={translateThis} disabled={busy}>
                {busy ? (
                  <IconLoaderCircle size={16} className="spin" />
                ) : (
                  <IconSparkles size={16} />
                )}{" "}
                {translateLabel}
              </button>
            ) : (
              <span className="small muted">
                <Link href="/login">Sign in</Link> to translate this chapter.
              </span>
            )}
          </div>
        )}

        {newTerms !== null && newTerms > 0 && (
          <p className="small new-terms">
            {newTerms} new glossary term{newTerms === 1 ? "" : "s"}
          </p>
        )}

        {chapter && view === "both" && chapter.translation && (
          <div className="grid-2">
            <div>
              <div className="small muted">Source</div>
              <div className="prose source">{chapter.source_text}</div>
            </div>
            <div>
              <div className="small muted">English</div>
              <div className="prose">
                <GlossaryText text={chapter.translation} terms={glossary} />
              </div>
            </div>
          </div>
        )}

        {chapter && view === "translation" && chapter.translation && (
          <div className="prose">
            <GlossaryText text={chapter.translation} terms={glossary} />
          </div>
        )}

        {chapter && view === "source" && (
          <div className="prose source">{chapter.source_text}</div>
        )}

        {chapter && chapter.translated_with && view !== "source" && (
          <p className="small muted" style={{ marginTop: 24 }}>
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

        <div className="reader-foot">{navButtons}</div>
      </article>

      <div className="reader-side">
        {signedIn && (
          <div className="panel">
            <h3 style={{ marginTop: 0, fontSize: 15 }}>
              <IconMessageCircleQuestionMark size={16} /> Ask about the story
            </h3>
            <p className="small muted">
              Answers only use chapters up to your reading position, so nothing
              ahead is spoiled.
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
            {askKeyNeeded && (
              <p className="small">
                <Link href="/settings">Add your API key</Link> to ask questions.
              </p>
            )}
            {askErr && <div className="error">{askErr}</div>}
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
        )}

        {novel && (
          <div className="panel">
            <h3 style={{ marginTop: 0, fontSize: 15 }}>
              <IconSettings size={16} /> Quick links
            </h3>
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
  );
}

export default function ReaderPage() {
  return (
    <Suspense fallback={<p className="muted">Loading...</p>}>
      <ReaderInner />
    </Suspense>
  );
}
