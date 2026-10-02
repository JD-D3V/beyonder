"use client";

import type { ReaderPrefs } from "../lib/readerPrefs";
import { IconMoon, IconSun, IconType, IconX } from "./icons";

export default function ReaderSettings({
  prefs,
  onChange,
  onClose,
}: {
  prefs: ReaderPrefs;
  onChange: (next: ReaderPrefs) => void;
  onClose: () => void;
}) {
  const set = <K extends keyof ReaderPrefs>(k: K, v: ReaderPrefs[K]) =>
    onChange({ ...prefs, [k]: v });

  return (
    <div className="reader-settings" role="dialog" aria-label="Reader settings">
      <div className="rs-head">
        <strong>Reader settings</strong>
        <button className="icon-btn" onClick={onClose} aria-label="Close settings">
          <IconX />
        </button>
      </div>

      <div className="rs-row">
        <span>Theme</span>
        <div className="seg">
          <button
            className={prefs.theme === "light" ? "on" : ""}
            onClick={() => set("theme", "light")}
          >
            <IconSun size={14} /> Light
          </button>
          <button
            className={prefs.theme === "sepia" ? "on" : ""}
            onClick={() => set("theme", "sepia")}
          >
            Sepia
          </button>
          <button
            className={prefs.theme === "dark" ? "on" : ""}
            onClick={() => set("theme", "dark")}
          >
            <IconMoon size={14} /> Dark
          </button>
        </div>
      </div>

      <div className="rs-row">
        <span>
          <IconType size={14} /> Font
        </span>
        <div className="seg">
          <button
            className={prefs.font === "serif" ? "on" : ""}
            onClick={() => set("font", "serif")}
          >
            Serif
          </button>
          <button
            className={prefs.font === "sans" ? "on" : ""}
            onClick={() => set("font", "sans")}
          >
            Sans
          </button>
        </div>
      </div>

      <label className="rs-row">
        <span>Size {prefs.size}px</span>
        <input
          type="range"
          min={14}
          max={26}
          step={1}
          value={prefs.size}
          onChange={(e) => set("size", Number(e.target.value))}
        />
      </label>

      <label className="rs-row">
        <span>Line height {prefs.lineHeight.toFixed(1)}</span>
        <input
          type="range"
          min={1.4}
          max={2.2}
          step={0.1}
          value={prefs.lineHeight}
          onChange={(e) => set("lineHeight", Number(e.target.value))}
        />
      </label>

      <label className="rs-row">
        <span>Width {prefs.width}px</span>
        <input
          type="range"
          min={560}
          max={960}
          step={20}
          value={prefs.width}
          onChange={(e) => set("width", Number(e.target.value))}
        />
      </label>
    </div>
  );
}
