// Free "Web" translation for the reader.
//
// Preferred: the browser's on-device Translator API (Chrome desktop). Fallback:
// the optional /mt proxy to a self-hosted LibreTranslate. The output is only
// ever shown and cached in this browser; it is never sent to the server and
// never counts as a saved translation. (Only the Chinese source goes to /mt in
// server mode, which is the point of that mode.)

import { API_BASE, type GlossaryEntry } from "./api";

export type WebMode = "browser" | "server";

export interface WebProgress {
  done: number;
  total: number;
  note?: string;
}

export interface WebTranslateOpts {
  // Chapter index: only glossary terms introduced by then are applied.
  chapter?: number;
  // Cache namespace, e.g. `${novelId}:${idx}`. Omit to skip the cache.
  cachePrefix?: string;
}

// Minimal types for the Translator API, which is not in the TS DOM lib yet.
interface TranslatorInstance {
  translate(text: string): Promise<string>;
}
interface TranslatorMonitor {
  addEventListener(type: "downloadprogress", cb: (e: { loaded: number }) => void): void;
}
interface TranslatorStatic {
  availability(o: { sourceLanguage: string; targetLanguage: string }): Promise<string>;
  create(o: {
    sourceLanguage: string;
    targetLanguage: string;
    monitor?: (m: TranslatorMonitor) => void;
  }): Promise<TranslatorInstance>;
}

const LANGS = { sourceLanguage: "zh", targetLanguage: "en" };
// /mt accepts 20 texts and 10,000 characters per request.
const MT_MAX_TEXTS = 20;
const MT_MAX_CHARS = 8000;

function translatorApi(): TranslatorStatic | null {
  const t = (globalThis as unknown as { Translator?: TranslatorStatic }).Translator;
  return t && typeof t.create === "function" ? t : null;
}

async function serverAvailable(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/mt/status`);
    if (!res.ok) return false;
    return Boolean((await res.json()).available);
  } catch {
    return false;
  }
}

let availability: Promise<WebMode | null> | null = null;

export function webTranslateAvailable(): Promise<WebMode | null> {
  if (!availability) {
    availability = (async () => {
      const T = translatorApi();
      if (T) {
        try {
          if ((await T.availability(LANGS)) !== "unavailable") return "browser";
        } catch {
          // fall through to the server
        }
      }
      return (await serverAvailable()) ? "server" : null;
    })();
  }
  return availability;
}

/** Paragraphs of source text: split on blank lines, empties dropped. */
export function splitParagraphs(text: string): string[] {
  return text.split(/\n[ \t]*\n+/).filter((p) => p.trim() !== "");
}

/** Web+: swap known glossary terms for their English before machine translation. */
export function applyGlossary(
  text: string,
  glossary: GlossaryEntry[],
  chapter?: number,
): string {
  const terms = glossary
    .filter(
      (g) =>
        g.source_term &&
        g.target_term &&
        (chapter === undefined || g.first_chapter <= chapter),
    )
    .sort((a, b) => b.source_term.length - a.source_term.length);
  let out = text;
  for (const g of terms) out = out.split(g.source_term).join(g.target_term);
  return out;
}

// --- translator back ends ---------------------------------------------------

let translator: Promise<TranslatorInstance> | null = null;
let onDownload: ((pct: number) => void) | null = null;

function getTranslator(T: TranslatorStatic): Promise<TranslatorInstance> {
  if (!translator) {
    translator = T.create({
      ...LANGS,
      monitor(m) {
        m.addEventListener("downloadprogress", (e) => onDownload?.(e.loaded));
      },
    });
    translator.catch(() => {
      translator = null;
    });
  }
  return translator;
}

async function viaBrowser(
  paras: string[],
  progress: (p: WebProgress) => void,
): Promise<string[]> {
  const T = translatorApi();
  if (!T) throw new Error("Browser translation is not available");
  onDownload = (loaded) =>
    progress({ done: 0, total: paras.length, note: `Downloading language pack ${Math.round(loaded * 100)}%` });
  const tr = await getTranslator(T);
  onDownload = null;
  const out: string[] = [];
  for (const p of paras) {
    out.push(await tr.translate(p));
    progress({ done: out.length, total: paras.length });
  }
  return out;
}

// Break an over-long paragraph at sentence ends so it fits a /mt request.
function chunkLong(p: string): string[] {
  if (p.length <= MT_MAX_CHARS) return [p];
  const out: string[] = [];
  let cur = "";
  for (const s of p.split(/(?<=[。！？!?；;\n])/)) {
    if (cur && cur.length + s.length > MT_MAX_CHARS) {
      out.push(cur);
      cur = "";
    }
    // A sentence longer than the cap is hard-cut.
    for (let i = 0; i < s.length; i += MT_MAX_CHARS) {
      const piece = s.slice(i, i + MT_MAX_CHARS);
      if (cur && cur.length + piece.length > MT_MAX_CHARS) {
        out.push(cur);
        cur = "";
      }
      cur += piece;
    }
  }
  if (cur) out.push(cur);
  return out;
}

async function viaServer(
  paras: string[],
  progress: (p: WebProgress) => void,
): Promise<string[]> {
  // Flatten to chunks, translate in batches, then stitch paragraphs back.
  const chunks: string[] = [];
  const owner: number[] = [];
  paras.forEach((p, i) =>
    chunkLong(p).forEach((c) => {
      chunks.push(c);
      owner.push(i);
    }),
  );
  const outChunks: string[] = [];
  let i = 0;
  while (i < chunks.length) {
    const batch: string[] = [];
    let chars = 0;
    while (
      i + batch.length < chunks.length &&
      batch.length < MT_MAX_TEXTS &&
      (batch.length === 0 || chars + chunks[i + batch.length].length <= MT_MAX_CHARS)
    ) {
      chars += chunks[i + batch.length].length;
      batch.push(chunks[i + batch.length]);
    }
    const res = await fetch(`${API_BASE}/mt/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texts: batch }),
    });
    if (!res.ok) {
      throw new Error(
        res.status === 429
          ? "Free translation is busy, try again in a few minutes"
          : "Free translation failed",
      );
    }
    const data = (await res.json()) as { texts: string[] };
    outChunks.push(...data.texts);
    i += batch.length;
    progress({ done: i, total: chunks.length });
  }
  const out: string[] = paras.map(() => "");
  outChunks.forEach((t, k) => {
    const o = owner[k];
    out[o] = out[o] ? `${out[o]} ${t}` : t;
  });
  return out;
}

// --- cache -------------------------------------------------------------------

async function sha1(text: string): Promise<string> {
  try {
    const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    // Insecure context: a cheap non-crypto hash is enough for a cache key.
    let h = 5381;
    for (let k = 0; k < text.length; k++) h = ((h << 5) + h + text.charCodeAt(k)) | 0;
    return `x${(h >>> 0).toString(16)}-${text.length}`;
  }
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("beyonder-webmt", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("t");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function cacheGet(key: string): Promise<string[] | null> {
  try {
    const db = await openDb();
    return await new Promise((resolve) => {
      const r = db.transaction("t").objectStore("t").get(key);
      r.onsuccess = () => resolve(Array.isArray(r.result) ? (r.result as string[]) : null);
      r.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

async function cacheSet(key: string, value: string[]): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve) => {
      const tx = db.transaction("t", "readwrite");
      tx.objectStore("t").put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    });
  } catch {
    // no IndexedDB (private mode, blocked): translate every time
  }
}

// --- public ------------------------------------------------------------------

/**
 * Translate Chinese paragraphs to English with the best free back end.
 * Returns one string per input paragraph. Throws if no back end is available
 * or the translation fails.
 */
export async function webTranslate(
  paragraphs: string[],
  glossary: GlossaryEntry[],
  onProgress?: (p: WebProgress) => void,
  opts: WebTranslateOpts = {},
): Promise<string[]> {
  const progress = onProgress ?? (() => undefined);
  const key = opts.cachePrefix
    ? `${opts.cachePrefix}:${await sha1(paragraphs.join("\n\n"))}`
    : null;
  if (key) {
    const hit = await cacheGet(key);
    if (hit && hit.length === paragraphs.length) return hit;
  }
  const mode = await webTranslateAvailable();
  if (!mode) throw new Error("Free translation needs desktop Chrome");
  const prepared = paragraphs.map((p) => applyGlossary(p, glossary, opts.chapter));
  let out: string[];
  if (mode === "browser") {
    try {
      out = await viaBrowser(prepared, progress);
    } catch (e) {
      // e.g. the language pack needs a click to download: use the proxy if any.
      if (!(await serverAvailable())) throw e;
      out = await viaServer(prepared, progress);
    }
  } else {
    out = await viaServer(prepared, progress);
  }
  if (key) await cacheSet(key, out);
  return out;
}
