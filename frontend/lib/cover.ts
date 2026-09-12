// Books imported as plain text have no cover art, and a shelf of identical grey
// rectangles is unreadable. Derive a stable one from the title instead: same
// title, same colours, every render, no storage and nothing to fetch.

function hash(text: string): number {
  let h = 2166136261; // FNV-1a
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

export interface Cover {
  background: string;
  monogram: string;
}

export function coverFor(title: string, id: number): Cover {
  const h = hash(`${title}#${id}`);
  const hue = h % 360;
  // Second hue is a fixed distance away, so the pair is always related rather
  // than random: analogous colours read as designed, opposites read as noise.
  const hue2 = (hue + 38) % 360;
  return {
    background: `linear-gradient(150deg, hsl(${hue} 58% 34%), hsl(${hue2} 62% 22%))`,
    monogram: monogramFor(title),
  };
}

// CJK titles carry their meaning in the first character or two, so take two.
// Latin titles read better as initials from the first words.
function monogramFor(title: string): string {
  const trimmed = title.trim();
  if (!trimmed) return "?";
  const isCjk = /[\u3400-\u9fff]/.test(trimmed);
  if (isCjk) {
    return Array.from(trimmed).slice(0, 2).join("");
  }
  const words = trimmed.split(/\s+/).filter((w) => /[a-z0-9]/i.test(w));
  if (words.length === 0) return Array.from(trimmed)[0].toUpperCase();
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}
