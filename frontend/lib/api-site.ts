import { req, type AuthUser, type Visibility } from "./api";

// Fields the backend adds to every catalog entry (views, ratings, cover).
export interface SiteStats {
  views_total?: number;
  rating_avg?: number | null;
  rating_count?: number;
  has_cover?: boolean;
  cover_version?: string | null;
}

export type RankPeriod = "day" | "week" | "month" | "all";

export interface RankedNovel extends SiteStats {
  id: number;
  title: string;
  title_en?: string | null;
  author: string | null;
  author_en?: string | null;
  views: number;
  rank: number;
}

export interface Invite {
  code: string;
  used: boolean;
  expires_at: string;
}

export interface AdminReport {
  id: number;
  kind: "review" | "comment";
  target_id: number;
  reporter: string;
  reason: string;
  created_at: string | null;
  resolved: boolean;
  target_body: string | null;
  target_author: string | null;
}

export interface ImportJob {
  id: number;
  novel_id: number | null;
  status: "queued" | "running" | "done" | "failed";
  total: number;
  done: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface MtStatus {
  status: "none" | "queued" | "running" | "done" | "failed" | "off" | string;
  done: number;
  total: number;
}

export const siteApi = {
  mtStatus: (novelId: number) => req<MtStatus>(`/novels/${novelId}/mt`),
  rerunMt: (novelId: number) =>
    req<MtStatus>(`/novels/${novelId}/mt`, { method: "POST" }),
  ingestToc: (body: {
    index_url: string;
    title?: string;
    max_chapters?: number;
    visibility?: Visibility;
  }) =>
    req<{ job_id: number }>("/novels/ingest/toc", { method: "POST", body: JSON.stringify(body) }),
  importJob: (id: number) => req<ImportJob>(`/imports/${id}`),
  myImports: () => req<ImportJob[]>("/imports?mine=true"),
  rankings: (period: RankPeriod, limit = 50) =>
    req<RankedNovel[]>(`/rankings?period=${period}&limit=${limit}`),
  listInvites: () => req<Invite[]>("/admin/invites"),
  createInvite: (days: number) =>
    req<{ code: string }>("/admin/invites", { method: "POST", body: JSON.stringify({ days }) }),
  listReports: (resolved = false) =>
    req<AdminReport[]>(`/admin/reports?resolved=${resolved}`),
  resolveReport: (id: number) =>
    req<{ ok: boolean }>(`/admin/reports/${id}/resolve`, { method: "POST" }),
  checkUpdates: (novelId: number) =>
    req<{ added: number; embedded?: boolean; hint?: string | null }>(`/novels/${novelId}/check-updates`, { method: "POST" }),
  setDisplayName: (display_name: string | null) =>
    req<AuthUser>("/auth/me", { method: "PATCH", body: JSON.stringify({ display_name }) }),
  deleteComment: (id: number) => req<void>(`/comments/${id}`, { method: "DELETE" }),
  deleteReview: (id: number) => req<void>(`/reviews/${id}`, { method: "DELETE" }),
};

export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}
