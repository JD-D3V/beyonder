"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import "../app/social.css";
import { errorText } from "../lib/api";
import { Rating, Review, social } from "../lib/api-social";
import type { Session } from "../lib/session";

const PAGE = 20;

export function Stars({ value }: { value: number }) {
  return (
    <span className="stars" aria-label={`${value} of 5 stars`}>
      {"★".repeat(value)}
      <span style={{ opacity: 0.3 }}>{"★".repeat(5 - value)}</span>
    </span>
  );
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

export default function Reviews({
  novelId,
  session,
}: {
  novelId: number;
  session: Session | null;
}) {
  const [rating, setRating] = useState<Rating | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const [mine, setMine] = useState<Review | null>(null);
  const [stars, setStars] = useState(0);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  const uid = session?.user.id ?? null;
  const isAdmin = Boolean(session?.user.is_admin);

  const loadRating = useCallback(async () => {
    try {
      setRating(await social.rating(novelId));
    } catch (e) {
      setErr(errorText(e));
    }
  }, [novelId]);

  const loadFirst = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await social.reviews(novelId, PAGE, 0);
      setReviews(rows);
      setMore(rows.length === PAGE);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [novelId]);

  useEffect(() => {
    loadRating();
    loadFirst();
  }, [loadRating, loadFirst]);

  // Find the signed-in reader's own review: in the loaded page if present,
  // otherwise page through until found.
  useEffect(() => {
    setMine(null);
    setStars(0);
    setText("");
    if (uid == null) return;
    let live = true;
    (async () => {
      try {
        for (let off = 0; off < 2000; off += 100) {
          const rows = await social.reviews(novelId, 100, off);
          const m = rows.find((r) => r.user_id === uid);
          if (m) {
            if (live) {
              setMine(m);
              setStars(m.rating);
              setText(m.body || "");
            }
            return;
          }
          if (rows.length < 100) return;
        }
      } catch {
        /* the list above reports errors */
      }
    })();
    return () => {
      live = false;
    };
  }, [novelId, uid]);

  async function loadMore() {
    try {
      const rows = await social.reviews(novelId, PAGE, reviews.length);
      setReviews((cur) => [...cur, ...rows.filter((r) => !cur.some((c) => c.id === r.id))]);
      setMore(rows.length === PAGE);
    } catch (e) {
      setErr(errorText(e));
    }
  }

  async function save() {
    if (stars < 1) {
      setErr("Pick a star rating first.");
      return;
    }
    setSaving(true);
    setErr(null);
    setNote(null);
    try {
      const r = await social.putReview(novelId, stars, text);
      setMine(r);
      setNote("Review saved.");
      await Promise.all([loadRating(), loadFirst()]);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function removeMine() {
    if (!window.confirm("Delete your review?")) return;
    setErr(null);
    try {
      await social.deleteOwnReview(novelId);
      setMine(null);
      setStars(0);
      setText("");
      setNote("Review deleted.");
      await Promise.all([loadRating(), loadFirst()]);
    } catch (e) {
      setErr(errorText(e));
    }
  }

  async function adminDelete(id: number) {
    if (!window.confirm("Delete this review?")) return;
    try {
      await social.deleteReview(id);
      await Promise.all([loadRating(), loadFirst()]);
    } catch (e) {
      setErr(errorText(e));
    }
  }

  async function report(id: number) {
    const reason = window.prompt("Why are you reporting this review? (optional)");
    if (reason === null) return;
    try {
      await social.report("review", id, reason.slice(0, 500));
      setNote("Thanks, the review was reported.");
    } catch (e) {
      setErr(errorText(e));
    }
  }

  const hist = rating?.histogram || {};
  const maxBin = Math.max(1, ...[1, 2, 3, 4, 5].map((k) => hist[String(k)] || 0));

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>Ratings and reviews</h3>
      <div className="rating-summary">
        <div className="rating-big">
          {rating && rating.average != null ? (
            <>
              <span className="stars">★</span> {rating.average.toFixed(1)}
            </>
          ) : (
            "—"
          )}
          <small>
            {rating?.count ?? 0} rating{rating?.count === 1 ? "" : "s"}
          </small>
        </div>
        <div className="hist">
          {[5, 4, 3, 2, 1].map((k) => {
            const n = hist[String(k)] || 0;
            return (
              <div className="hist-row" key={k}>
                <span>{k}★</span>
                <span className="bar">
                  <i style={{ width: `${(n / maxBin) * 100}%` }} />
                </span>
                <span className="n">{n}</span>
              </div>
            );
          })}
        </div>
      </div>

      {err && <div className="error">{err}</div>}
      {note && <p className="small muted">{note}</p>}

      {session ? (
        <div className="social-form" style={{ marginBottom: 12 }}>
          <div className="small muted">{mine ? "Your review" : "Write a review"}</div>
          <div className="star-pick" role="radiogroup" aria-label="Your rating">
            {[1, 2, 3, 4, 5].map((k) => (
              <button
                key={k}
                type="button"
                className={k <= stars ? "on" : ""}
                onClick={() => setStars(k)}
                role="radio"
                aria-checked={k === stars}
                aria-label={`${k} star${k === 1 ? "" : "s"}`}
              >
                ★
              </button>
            ))}
          </div>
          <textarea
            maxLength={5000}
            placeholder="What did you think? (optional)"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="row">
            <button onClick={save} disabled={saving || stars < 1}>
              {saving ? "Saving..." : mine ? "Update review" : "Post review"}
            </button>
            {mine && (
              <button className="secondary" onClick={removeMine}>
                Delete
              </button>
            )}
            <span className="small muted">{text.length}/5000</span>
          </div>
        </div>
      ) : (
        <p className="small muted">
          <Link href="/login">Sign in</Link> to rate and review this book.
        </p>
      )}

      {loading && reviews.length === 0 && <p className="muted small">Loading reviews...</p>}
      {!loading && reviews.length === 0 && <p className="muted small">No reviews yet.</p>}
      {reviews.map((r) => (
        <div className="social-item" key={r.id}>
          <div className="meta">
            <Stars value={r.rating} />
            <b>{r.author}</b>
            <span>{fmtDate(r.updated_at || r.created_at)}</span>
          </div>
          {r.body && <div className="body">{r.body}</div>}
          <div className="acts">
            {session && r.user_id !== uid && (
              <button className="link-btn" onClick={() => report(r.id)}>
                Report
              </button>
            )}
            {isAdmin && r.user_id !== uid && (
              <button className="link-btn" onClick={() => adminDelete(r.id)}>
                Delete (admin)
              </button>
            )}
          </div>
        </div>
      ))}
      {more && (
        <div className="row" style={{ justifyContent: "center", marginTop: 8 }}>
          <button className="secondary" onClick={loadMore}>
            Load more
          </button>
        </div>
      )}
    </div>
  );
}
