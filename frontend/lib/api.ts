import { getLlmConfig } from "./llmKey";
import { announceUnauthorized, clearSession, getSession } from "./session";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Chapters up to this many source characters use /translate (whole-chapter,
// with the critic). Longer ones would blow a single request, so the UI drives
// them through /translate/step: resumable, piece-by-piece, no critic.
export const CRITIC_MAX_CHARS = 2500;

// Thrown when an AI route needs a key and none is saved, or the server says
// so (402). Pages can send the reader to Settings.
export class KeyRequiredError extends Error {
  constructor(message = "Add your AI key in Settings to use this.") {
    super(message);
    this.name = "KeyRequiredError";
  }
}

// Any other non-2xx response, with the HTTP status and the server's
// machine-readable code (from {"detail": {"code", ...}}) when it sent one.
export class ApiError extends Error {
  status: number;
  code: string | null;
  constructor(message: string, status: number, code: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export class UnauthorizedError extends Error {
  constructor(message = "Please sign in.") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

// Text to show a user for a caught error: the message, without a class prefix.
export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const AI_ROUTES = new Set(["/ask", "/translate", "/translate/batch", "/translate/step"]);

// Only these routes receive the user's AI key (query string ignored).
function isAiRoute(path: string): boolean {
  const p = path.split("?")[0];
  return AI_ROUTES.has(p) || /^\/novels\/\d+\/titles\/translate$/.test(p);
}

function authHeaders(): Record<string, string> {
  const s = getSession();
  return s ? { Authorization: `Bearer ${s.token}` } : {};
}

function llmHeaders(path: string): Record<string, string> {
  if (!isAiRoute(path)) return {};
  const c = getLlmConfig();
  if (!c) return {};
  const h: Record<string, string> = {
    "X-LLM-Provider": c.provider,
    "X-LLM-Key": c.key,
  };
  if (c.model) h["X-LLM-Model"] = c.model;
  return h;
}

// Handles {"detail": {"code", "detail"}}, {"detail": "text"} and FastAPI
// validation arrays.
function errorCode(body: unknown): string | null {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (d && typeof d === "object" && !Array.isArray(d) && "code" in d) {
    return String((d as { code: unknown }).code);
  }
  return null;
}

function errorMessage(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    const parts = d.map((e) =>
      e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : "",
    );
    const joined = parts.filter(Boolean).join("; ");
    return joined || fallback;
  }
  if (d && typeof d === "object" && "detail" in d) {
    return String((d as { detail: unknown }).detail);
  }
  return fallback;
}

async function check(res: Response, signedIn: boolean): Promise<void> {
  if (res.ok) return;
  const body = await res.json().catch(() => null);
  const fallback = `${res.status} ${res.statusText}`;
  const msg = errorMessage(body, fallback);
  if (res.status === 402) throw new KeyRequiredError(msg);
  if (res.status === 401) {
    // Only wipe the session if we had sent one; a failed login is also a 401.
    if (signedIn) clearSession();
    announceUnauthorized();
    throw new UnauthorizedError(msg);
  }
  throw new ApiError(msg, res.status, errorCode(body));
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = authHeaders();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...auth,
      ...llmHeaders(path),
      ...(init?.headers || {}),
    },
  });
  await check(res, "Authorization" in auth);
  // 204 No Content (e.g. DELETE /library/{id}) and empty bodies have no JSON.
  if (res.status === 204) return undefined as T;
  const raw = await res.text();
  return (raw ? JSON.parse(raw) : undefined) as T;
}

export interface AuthUser {
  id: number;
  email: string;
  is_admin: boolean;
}

export interface AuthResult {
  token: string;
  user: AuthUser;
}

export interface Novel {
  id: number;
  title: string;
  title_en?: string | null;
  author: string | null;
  description: string | null;
  tags: string[];
  status: string;
  source_lang: string;
  source_url: string | null;
  chapter_count: number;
  char_count: number;
  translated_count: number;
  updated_at: string | null;
}

export interface ChapterRow {
  idx: number;
  title: string | null;
  title_en?: string | null;
  char_count: number;
  translated: boolean; // complete only
  pieces_done: number | null; // set while a resumable translation is mid-flight
}

export interface ChapterDetail {
  idx: number;
  title: string | null;
  title_en?: string | null;
  char_count: number;
  source_text: string;
  translation: string | null;
  translated_with: string | null;
  critic_passes: number | null;
  complete: boolean; // a full translation exists
  pieces_done: number | null;
}

export interface GlossaryEntry {
  id?: number | null;
  locked?: boolean;
  source_term: string;
  target_term: string;
  kind: string;
  first_chapter: number;
  confidence: number;
}

export interface Citation {
  chapter_idx: number;
  char_start: number;
  char_end: number;
  text: string;
  score: number;
}

export interface AskOut {
  answer: string;
  citations: Citation[];
}

export interface KgNode {
  id: string;
  label: string;
  kind: string;
  first_chapter: number;
}

export interface KgEdge {
  src: string;
  dst: string;
  relation: string;
  first_chapter: number;
}

export interface KgOut {
  nodes: KgNode[];
  edges: KgEdge[];
}

export interface TranslateResult {
  chapter_idx: number;
  translation: string;
  new_terms: GlossaryEntry[];
  critic_passes: number;
  title_en?: string | null;
}

export interface TranslateBatchResult {
  translated: number[];
  remaining: number;
  done: boolean;
  error: string | null;
}

export interface TranslateStepResult {
  chapter_idx: number;
  pieces_done: number;
  pieces_total: number;
  complete: boolean;
  // A piece came back blank this call without a model error (key, rate-limit
  // and outage errors are thrown as ApiError). No progress; pause and retry.
  stalled: boolean;
  new_terms?: GlossaryEntry[];
  title_en?: string | null;
}

export type Shelf = "reading" | "plan" | "completed";

export interface LibraryItem extends Novel {
  current_chapter: number;
}

export interface LibraryOut {
  reading: LibraryItem[];
  plan: LibraryItem[];
  completed: LibraryItem[];
}

export interface ReviewFlag {
  id: number;
  novel_id: number;
  chapter_idx: number;
  kind: string;
  source_span: string;
  target_span: string;
  note: string;
  status: string;
  created_at: string | null;
  resolved_by: number | null;
}

export interface NovelQuery {
  q?: string;
  tag?: string;
  status?: string;
  min_chapters?: number;
  max_chapters?: number;
  sort?: "updated" | "new" | "chapters";
  limit?: number;
  offset?: number;
}

export interface IngestResult {
  novel_id: number;
  chapters_added: number;
  title: string | null;
}

export interface NovelPatch {
  title?: string;
  title_en?: string;
  author?: string;
  description?: string;
  tags?: string[];
  status?: string;
  source_lang?: string;
}

// Translated title when present, else the source title; the source title goes
// in `hover` when both exist and differ.
export function displayTitle(
  src: string | null | undefined,
  en: string | null | undefined,
): { text: string; hover?: string } {
  const e = (en ?? "").trim();
  const t = (src ?? "").trim();
  if (e) return t && t !== e ? { text: e, hover: t } : { text: e };
  return { text: t };
}

export const api = {
  health: () =>
    req<{ ok: boolean; commit?: string; model?: string; embed_model?: string }>(
      "/health",
    ),

  // --- library ---
  listNovels: (query: NovelQuery = {}) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== "" && v !== null) sp.set(k, String(v));
    }
    const qs = sp.toString();
    return req<Novel[]>(`/novels${qs ? `?${qs}` : ""}`);
  },
  getNovel: (id: number) => req<Novel>(`/novels/${id}`),
  patchNovel: (id: number, body: NovelPatch) =>
    req<Novel>(`/novels/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteNovel: (id: number) =>
    req<{ ok: boolean; deleted: number }>(`/novels/${id}`, { method: "DELETE" }),

  // --- chapters ---
  listChapters: (id: number, targetLang = "en") =>
    req<ChapterRow[]>(`/novels/${id}/chapters?target_lang=${targetLang}`),
  getChapter: (id: number, idx: number, targetLang = "en") =>
    req<ChapterDetail>(`/novels/${id}/chapters/${idx}?target_lang=${targetLang}`),

  // --- import ---
  ingestText: (body: {
    title: string;
    text: string;
    source_lang?: string;
    source_url?: string;
    author?: string;
    description?: string;
    tags?: string[];
  }) =>
    req<IngestResult>("/novels/ingest/text", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ingestUrl: (body: { title: string; urls: string[]; source_lang?: string }) =>
    req<IngestResult>("/novels/ingest/url", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  // Multipart: the browser sets its own content-type with the boundary, so this
  // one cannot go through req().
  uploadFile: async (
    file: File,
    meta: {
      title?: string;
      author?: string;
      description?: string;
      tags?: string;
      source_lang?: string;
    },
  ): Promise<IngestResult> => {
    const form = new FormData();
    form.append("file", file);
    for (const [k, v] of Object.entries(meta)) {
      if (v) form.append(k, v);
    }
    const auth = authHeaders();
    const res = await fetch(`${API_BASE}/novels/upload`, {
      method: "POST",
      // No content-type here: the browser sets it with the multipart boundary.
      headers: auth,
      body: form,
    });
    await check(res, "Authorization" in auth);
    return (await res.json()) as IngestResult;
  },

  // --- work ---
  embed: (body: { novel_id: number; from_chapter?: number; to_chapter?: number }) =>
    req<{ points: number }>("/novels/embed", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  // force: admin-only re-translate of a complete chapter (ignored otherwise).
  translate: (body: {
    novel_id: number;
    chapter_idx: number;
    target_lang?: string;
    force?: boolean;
  }) =>
    req<TranslateResult>("/translate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  translateBatch: (body: {
    novel_id: number;
    limit?: number;
    target_lang?: string;
  }) =>
    req<TranslateBatchResult>("/translate/batch", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  // One resumable pass over a long chapter. Call until `complete`.
  // force (admin, first call only): delete the saved translation and restart.
  translateStep: (body: {
    novel_id: number;
    chapter_idx: number;
    target_lang?: string;
    force?: boolean;
  }) =>
    req<TranslateStepResult>("/translate/step", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  translateTitles: (novelId: number) =>
    req<{ chapters: number; novel: boolean }>(`/novels/${novelId}/titles/translate`, {
      method: "POST",
    }),
  ask: (body: {
    novel_id: number;
    question: string;
    answer_lang?: string;
    top_k?: number;
  }) => req<AskOut>("/ask", { method: "POST", body: JSON.stringify(body) }),
  // up_to omitted: the server caps signed-in readers at their own progress.
  glossary: (novelId: number, upTo?: number) =>
    req<GlossaryEntry[]>(
      `/novels/${novelId}/glossary${upTo === undefined ? "" : `?up_to=${upTo}`}`,
    ),
  kg: (novelId: number, upTo?: number) =>
    req<KgOut>(
      `/novels/${novelId}/kg${upTo === undefined ? "" : `?up_to=${upTo}`}`,
    ),
  setProgress: (body: { novel_id: number; current_chapter: number }) =>
    req<{ ok: boolean }>("/progress", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getProgress: (novelId: number) =>
    req<{ novel_id: number; current_chapter: number }>(
      `/progress?novel_id=${novelId}`,
    ),

  // --- shelves, flags, glossary edits ---
  library: () => req<LibraryOut>("/library"),
  setShelf: (novelId: number, shelf: Shelf) =>
    req<unknown>(`/library/${novelId}`, {
      method: "PUT",
      body: JSON.stringify({ shelf }),
    }),
  removeFromLibrary: (novelId: number) =>
    req<unknown>(`/library/${novelId}`, { method: "DELETE" }),
  flags: (
    novelId: number,
    status: string = "open",
    upTo?: number,
    chapter?: number,
  ) => {
    const sp = new URLSearchParams({ status });
    if (upTo !== undefined) sp.set("up_to", String(upTo));
    if (chapter !== undefined) sp.set("chapter", String(chapter));
    return req<ReviewFlag[]>(`/novels/${novelId}/flags?${sp.toString()}`);
  },
  resolveFlag: (flagId: number, wrongRendering?: string) =>
    req<unknown>(`/flags/${flagId}/resolve`, {
      method: "POST",
      body: JSON.stringify(wrongRendering ? { wrong_rendering: wrongRendering } : {}),
    }),
  patchGlossaryTerm: (
    novelId: number,
    termId: number,
    body: { target_term?: string; locked?: boolean },
  ) =>
    req<unknown>(`/novels/${novelId}/glossary/${termId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  // --- accounts ---
  login: (body: { email: string; password: string }) =>
    req<AuthResult>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  signup: (body: { email: string; password: string; invite: string }) =>
    req<AuthResult>("/auth/signup", { method: "POST", body: JSON.stringify(body) }),
  logout: () => req<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  me: () => req<AuthUser>("/auth/me"),
};
