export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return (await res.json()) as T;
}

export interface Novel {
  id: number;
  title: string;
  source_lang: string;
  source_url: string | null;
  chapter_count: number;
}

export interface GlossaryEntry {
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
  new_terms: number;
  critic_passes: number;
}

export const api = {
  health: () => req<{ ok: boolean }>("/health"),
  listNovels: () => req<Novel[]>("/novels"),
  ingestText: (body: {
    title: string;
    text: string;
    source_lang?: string;
    source_url?: string;
  }) => req<{ novel_id: number; chapters_added: number }>("/novels/ingest/text", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  ingestUrl: (body: { title: string; urls: string[]; source_lang?: string }) =>
    req<{ novel_id: number; chapters_added: number }>("/novels/ingest/url", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  embed: (body: { novel_id: number; from_chapter?: number; to_chapter?: number }) =>
    req<{ points: number }>("/novels/embed", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  translate: (body: { novel_id: number; chapter_idx: number; target_lang?: string }) =>
    req<TranslateResult>("/translate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ask: (body: {
    novel_id: number;
    question: string;
    current_chapter: number;
    answer_lang?: string;
    top_k?: number;
  }) => req<AskOut>("/ask", { method: "POST", body: JSON.stringify(body) }),
  glossary: (novelId: number, upTo: number = 100000) =>
    req<GlossaryEntry[]>(`/novels/${novelId}/glossary?up_to=${upTo}`),
  kg: (novelId: number, upTo: number = 100000) =>
    req<KgOut>(`/novels/${novelId}/kg?up_to=${upTo}`),
  setProgress: (body: { handle?: string; novel_id: number; current_chapter: number }) =>
    req<{ ok: boolean }>("/progress", {
      method: "POST",
      body: JSON.stringify({ handle: body.handle ?? "demo", ...body }),
    }),
};
