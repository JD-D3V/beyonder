import { coverFor } from "../lib/cover";

export default function BookCover({
  title,
  id,
  size = "md",
}: {
  title: string;
  id: number;
  size?: "sm" | "md" | "lg";
}) {
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
