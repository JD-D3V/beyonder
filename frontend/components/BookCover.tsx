import { API_BASE } from "../lib/api";
import { coverFor } from "../lib/cover";

export default function BookCover({
  title,
  id,
  size = "md",
  hasCover = false,
  coverVersion,
}: {
  title: string;
  id: number;
  size?: "sm" | "md" | "lg";
  hasCover?: boolean;
  coverVersion?: string | null;
}) {
  if (hasCover) {
    const v = coverVersion ? `?v=${encodeURIComponent(coverVersion)}` : "";
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
