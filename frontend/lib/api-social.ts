import { API_BASE, req } from "./api";
import { getSession } from "./session";

export interface Rating {
  average: number | null;
  count: number;
  histogram: Record<string, number>;
}

export interface Review {
  id: number;
  user_id: number;
  author: string;
  rating: number;
  body: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Comment {
  id: number;
  chapter_idx: number;
  parent_id: number | null;
  user_id: number | null;
  author: string | null;
  body: string;
  deleted: boolean;
  created_at: string | null;
  replies: Comment[];
}

export const social = {
  rating: (novelId: number) => req<Rating>(`/novels/${novelId}/rating`),
  reviews: (novelId: number, limit = 20, offset = 0) =>
    req<Review[]>(`/novels/${novelId}/reviews?limit=${limit}&offset=${offset}`),
  putReview: (novelId: number, rating: number, body: string) =>
    req<Review>(`/novels/${novelId}/review`, {
      method: "PUT",
      body: JSON.stringify({ rating, body: body.trim() || null }),
    }),
  deleteOwnReview: (novelId: number) =>
    req<void>(`/novels/${novelId}/review`, { method: "DELETE" }),
  deleteReview: (reviewId: number) =>
    req<void>(`/reviews/${reviewId}`, { method: "DELETE" }),

  comments: (novelId: number, idx: number) =>
    req<Comment[]>(`/novels/${novelId}/chapters/${idx}/comments`),
  postComment: (novelId: number, idx: number, body: string, parentId?: number | null) =>
    req<Comment>(`/novels/${novelId}/chapters/${idx}/comments`, {
      method: "POST",
      body: JSON.stringify({ body, parent_id: parentId ?? null }),
    }),
  deleteComment: (id: number) => req<void>(`/comments/${id}`, { method: "DELETE" }),

  report: (kind: "review" | "comment", targetId: number, reason = "") =>
    req<{ ok: boolean }>(`/reports`, {
      method: "POST",
      body: JSON.stringify({ kind, target_id: targetId, reason }),
    }),

  // Admin cover controls.
  setCoverUrl: (novelId: number, url: string) =>
    req<unknown>(`/novels/${novelId}/cover`, {
      method: "PUT",
      body: JSON.stringify({ url }),
    }),
  removeCover: (novelId: number) =>
    req<unknown>(`/novels/${novelId}/cover`, { method: "DELETE" }),
  // Multipart: the browser must set the content-type (with its boundary), so
  // this one bypasses req's JSON default header.
  async uploadCover(novelId: number, file: File): Promise<void> {
    const s = getSession();
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/novels/${novelId}/cover`, {
      method: "PUT",
      headers: s ? { Authorization: `Bearer ${s.token}` } : {},
      body: fd,
    });
    if (!res.ok) {
      const b = await res.json().catch(() => null);
      const d = b?.detail;
      throw new Error(
        typeof d === "string" ? d : d?.detail || `${res.status} ${res.statusText}`,
      );
    }
  },
};
