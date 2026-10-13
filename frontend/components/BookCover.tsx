"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "../lib/api";
import { coverFor } from "../lib/cover";
import { getSession } from "../lib/session";

function Monogram({ title, id, size }: { title: string; id: number; size: string }) {
  const cover = coverFor(title, id);
  return (
    <div
      className={`cover cover-${size}`}
      style={{ background: cover.background }}
      aria-hidden="true"
    >
      <span className="cover-monogram">{cover.monogram}</span>
    </div>
  );
}

// An <img> cannot send the bearer token, and a private book's cover is only
// served to its owner and admins. Fetch it with the token and show the blob.
function PrivateCover({
  title,
  id,
  size,
  v,
}: {
  title: string;
  id: number;
  size: string;
  v: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    const s = getSession();
    if (!s) return;
    let url: string | null = null;
    let dead = false;
    fetch(`${API_BASE}/novels/${id}/cover${v}`, {
      headers: { Authorization: `Bearer ${s.token}` },
    })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => {
        if (!b || dead) return;
        url = URL.createObjectURL(b);
        setSrc(url);
      })
      .catch(() => undefined);
    return () => {
      dead = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, v]);
  if (!src) return <Monogram title={title} id={id} size={size} />;
  return (
    <div className={`cover cover-${size} cover-img`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={`Cover of ${title}`} decoding="async" />
    </div>
  );
}

export default function BookCover({
  title,
  id,
  size = "md",
  hasCover = false,
  coverVersion,
  visibility = "public",
}: {
  title: string;
  id: number;
  size?: "sm" | "md" | "lg";
  hasCover?: boolean;
  coverVersion?: string | null;
  visibility?: "public" | "private";
}) {
  if (hasCover) {
    const v = coverVersion ? `?v=${encodeURIComponent(coverVersion)}` : "";
    if (visibility === "private") {
      return <PrivateCover title={title} id={id} size={size} v={v} />;
    }
    return (
      <div className={`cover cover-${size} cover-img`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`${API_BASE}/novels/${id}/cover${v}`}
          alt={`Cover of ${title}`}
          loading="lazy"
          decoding="async"
        />
      </div>
    );
  }
  return <Monogram title={title} id={id} size={size} />;
}
