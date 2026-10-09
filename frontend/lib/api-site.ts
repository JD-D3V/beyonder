import { req, type AuthUser } from "./api";

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

export const siteApi = {
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
