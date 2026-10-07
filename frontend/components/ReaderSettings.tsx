"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  DEFAULT_PREFS,
  FONT_LABELS,
  FONT_STACKS,
  THEME_ORDER,
  THEME_SWATCHES,
  type BracketsStyle,
  type ReaderFont,
  type ReaderPrefs,
  type ReaderTheme,
} from "../lib/readerPrefs";
import { applyTextStyle } from "../lib/textStyle";
import { IconX } from "./icons";

type View = "translation" | "source" | "both";

const FONT_ORDER: ReaderFont[] = ["nunito", "roboto", "lora", "lexend", "atkinson", "serif", "sans"];

const THEME_NAMES: Record<ReaderTheme, string> = {
  white: "White",
  cream: "Cream",
  tan: "Tan",
  blue: "Blue",
  pink: "Pink",
  green: "Green",
  dark: "Dark",
  custom: "Custom",
};

const SAMPLE =
  "“It’s the Azure Sect,” he said. \"Don't run.\" 【Ancient Technique】 [Realm: Qi Condensation] 『Heavenly Seal』 gleamed in the dark.";

function IconPalette({ size = 18 }: { size?: number }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="icon"
    >
      <path d="M12 22a1 1 0 0 1 0-20 10 9 0 0 1 10 9 5 5 0 0 1-5 5h-2.25a1.75 1.75 0 0 0-1.4 2.8l.3.4a1.75 1.75 0 0 1-1.4 2.8z" />
      <circle cx="13.5" cy="6.5" r=".5" fill="currentColor" />
      <circle cx="17.5" cy="10.5" r=".5" fill="currentColor" />
      <circle cx="6.5" cy="12.5" r=".5" fill="currentColor" />
      <circle cx="8.5" cy="7.5" r=".5" fill="currentColor" />
    </svg>
  );
}

function Seg<T extends string>({
  label,
  value,
  options,
  onPick,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; style?: CSSProperties }[];
  onPick: (v: T) => void;
}) {
  return (
    <div className="rset-group" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={value === o.value ? "on" : ""}
          aria-pressed={value === o.value}
          style={o.style}
          onClick={() => onPick(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function previewVars(p: ReaderPrefs): CSSProperties {
  const v: Record<string, string> = {
    "--r-font": FONT_STACKS[p.font],
    "--r-size": `${p.size}px`,
    "--r-lh": String(p.lineHeight),
    "--r-width": `${p.width}px`,
    "--r-para": `${p.paragraphSpacing}em`,
    "--r-align": p.align,
  };
  if (p.theme === "custom") {
    v["--r-bg"] = p.customBg;
    v["--r-page"] = p.customBg;
    v["--r-fg"] = p.customFg;
  }
  return v as CSSProperties;
}

function Advanced({
  prefs,
  onSave,
  onCancel,
}: {
  prefs: ReaderPrefs;
  onSave: (p: ReaderPrefs) => void;
  onCancel: () => void;
}) {
  const [d, setD] = useState<ReaderPrefs>(prefs);
  const ref = useRef<HTMLDivElement>(null);
  const set = <K extends keyof ReaderPrefs>(k: K, v: ReaderPrefs[K]) =>
    setD((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      prev?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const custom = d.theme === "custom";
  const brackets: { value: BracketsStyle; label: string }[] = [
    { value: "corner", label: "【Corner】" },
    { value: "regular", label: "[Regular]" },
    { value: "semicorner", label: "『Semi-Corner』" },
  ];

  return (
    <div className="rset-overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div
        className="rset-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rset-adv-title"
        tabIndex={-1}
        ref={ref}
      >
        <div className="rset-head">
          <strong id="rset-adv-title">Advanced settings</strong>
          <button className="icon-btn" type="button" onClick={onCancel} aria-label="Cancel">
            <IconX />
          </button>
        </div>

        <div className="rset-body">
          <div className="rset-row">
            <span>Quotes</span>
            <Seg
              label="Quotes"
              value={d.quotes}
              options={[
                { value: "regular", label: "Regular" },
                { value: "smart", label: "Smart" },
              ]}
              onPick={(v) => set("quotes", v)}
            />
          </div>
          <div className="rset-row">
            <span>Brackets</span>
            <Seg label="Brackets" value={d.brackets} options={brackets} onPick={(v) => set("brackets", v)} />
          </div>
          <label className="rset-row">
            <span>Width {d.width}px</span>
            <input
              type="range"
              min={520}
              max={1100}
              step={20}
              value={d.width}
              onChange={(e) => set("width", Number(e.target.value))}
            />
          </label>
          <label className="rset-row">
            <span>Paragraph spacing {d.paragraphSpacing}em</span>
            <input
              type="range"
              min={0}
              max={2}
              step={0.25}
              value={d.paragraphSpacing}
              onChange={(e) => set("paragraphSpacing", Number(e.target.value))}
            />
          </label>
          <div className="rset-row">
            <span>Alignment</span>
            <Seg
              label="Alignment"
              value={d.align}
              options={[
                { value: "left", label: "Left" },
                { value: "justify", label: "Justify" },
              ]}
              onPick={(v) => set("align", v)}
            />
          </div>

          <div className="rset-row">
            <span>Custom theme</span>
            <Seg
              label="Custom theme"
              value={custom ? "on" : "off"}
              options={[
                { value: "on", label: "Enabled" },
                { value: "off", label: "Disabled" },
              ]}
              onPick={(v) =>
                set("theme", v === "on" ? "custom" : prefs.theme === "custom" ? "dark" : prefs.theme)
              }
            />
          </div>
          {custom && (
            <div className="rset-colors">
              <label>
                <span>Background</span>
                <input
                  type="color"
                  value={d.customBg}
                  onChange={(e) => set("customBg", e.target.value)}
                />
              </label>
              <label>
                <span>Text</span>
                <input
                  type="color"
                  value={d.customFg}
                  onChange={(e) => set("customFg", e.target.value)}
                />
              </label>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  setD((x) => ({
                    ...x,
                    customBg: DEFAULT_PREFS.customBg,
                    customFg: DEFAULT_PREFS.customFg,
                  }))
                }
              >
                Reset to default
              </button>
            </div>
          )}

          <div className="rset-label">Preview</div>
          <div
            className="reader-root rset-preview"
            data-theme={d.theme}
            style={previewVars(d)}
            aria-label="Preview"
          >
            <div className="reader-text prose">
              <p>{applyTextStyle(SAMPLE, { quotes: d.quotes, brackets: d.brackets })}</p>
              <p>{applyTextStyle("The second paragraph shows spacing and alignment.", d)}</p>
            </div>
          </div>
        </div>

        <div className="rset-foot">
          <button type="button" className="secondary" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" onClick={() => onSave(d)}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ReaderSettings({
  prefs,
  onChange,
  onClose,
  view,
  onViewChange,
}: {
  prefs: ReaderPrefs;
  onChange: (next: ReaderPrefs) => void;
  onClose: () => void;
  view?: View;
  onViewChange?: (v: View) => void;
}) {
  const [tab, setTab] = useState<"display" | "settings">("display");
  const [advanced, setAdvanced] = useState(false);
  const set = <K extends keyof ReaderPrefs>(k: K, v: ReaderPrefs[K]) =>
    onChange({ ...prefs, [k]: v });
  const step = (k: "size" | "lineHeight", delta: number, min: number, max: number) => {
    const next = Math.min(max, Math.max(min, prefs[k] + delta));
    set(k, Math.round(next * 10) / 10);
  };

  useEffect(() => {
    if (advanced) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [advanced, onClose]);

  return (
    <>
      <div className="rset" role="dialog" aria-label="Reader settings">
        <div className="rset-head">
          <div className="rset-tabs" role="group" aria-label="Settings tabs">
            <button
              type="button"
              className={tab === "display" ? "on" : ""}
              aria-pressed={tab === "display"}
              onClick={() => setTab("display")}
            >
              Display
            </button>
            <button
              type="button"
              className={tab === "settings" ? "on" : ""}
              aria-pressed={tab === "settings"}
              onClick={() => setTab("settings")}
            >
              Settings
            </button>
          </div>
          <button className="secondary" type="button" onClick={() => setAdvanced(true)}>
            Advanced
          </button>
          <button className="icon-btn" type="button" onClick={onClose} aria-label="Close settings">
            <IconX />
          </button>
        </div>

        {tab === "display" ? (
          <div className="rset-body">
            <div className="rset-label">Font</div>
            <div className="rset-fonts" role="group" aria-label="Font">
              {FONT_ORDER.map((f) => (
                <button
                  key={f}
                  type="button"
                  className={prefs.font === f ? "on" : ""}
                  aria-pressed={prefs.font === f}
                  style={{ fontFamily: FONT_STACKS[f] }}
                  onClick={() => set("font", f)}
                >
                  {FONT_LABELS[f]}
                </button>
              ))}
            </div>

            <div className="rset-label">Font size</div>
            <div className="rset-stepper">
              <button
                type="button"
                className="secondary"
                onClick={() => step("size", -1, 12, 32)}
                disabled={prefs.size <= 12}
                aria-label="Decrease font size"
              >
                A-
              </button>
              <span aria-live="polite">{prefs.size}px</span>
              <button
                type="button"
                className="secondary"
                onClick={() => step("size", 1, 12, 32)}
                disabled={prefs.size >= 32}
                aria-label="Increase font size"
              >
                A+
              </button>
            </div>

            <div className="rset-label">Line height</div>
            <div className="rset-stepper">
              <button
                type="button"
                className="secondary"
                onClick={() => step("lineHeight", -0.1, 1.2, 2.4)}
                disabled={prefs.lineHeight <= 1.2}
              >
                Height -
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => set("lineHeight", DEFAULT_PREFS.lineHeight)}
                aria-label={`Line height ${prefs.lineHeight.toFixed(1)}, reset to default`}
              >
                {prefs.lineHeight.toFixed(1)} Default
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => step("lineHeight", 0.1, 1.2, 2.4)}
                disabled={prefs.lineHeight >= 2.4}
              >
                Height +
              </button>
            </div>

            <div className="rset-label">Term colors</div>
            <Seg
              label="Term colors"
              value={prefs.termColors ? "on" : "off"}
              options={[
                { value: "on", label: "Enabled" },
                { value: "off", label: "Disabled" },
              ]}
              onPick={(v) => set("termColors", v === "on")}
            />
          </div>
        ) : (
          <div className="rset-body">
            <div className="rset-label">Reader theme</div>
            <div className="rset-themes" role="group" aria-label="Reader theme">
              {THEME_ORDER.map((t) => {
                const sw =
                  t === "custom"
                    ? { bg: prefs.customBg, fg: prefs.customFg }
                    : THEME_SWATCHES[t];
                return (
                  <button
                    key={t}
                    type="button"
                    className={`rset-swatch${prefs.theme === t ? " on" : ""}`}
                    aria-pressed={prefs.theme === t}
                    aria-label={`${THEME_NAMES[t]} theme`}
                    title={THEME_NAMES[t]}
                    style={{ background: sw.bg, color: sw.fg }}
                    onClick={() => set("theme", t)}
                  >
                    {t === "custom" ? <IconPalette size={18} /> : "Aa"}
                  </button>
                );
              })}
            </div>

            <div className="rset-label">Reader type</div>
            <Seg
              label="Reader type"
              value={prefs.readerType}
              options={[
                { value: "single", label: "Single Page" },
                { value: "infinite", label: "Infinite" },
              ]}
              onPick={(v) => set("readerType", v)}
            />

            {view && onViewChange && (
              <>
                <div className="rset-label">View</div>
                <Seg
                  label="View"
                  value={view}
                  options={[
                    { value: "translation", label: "Translation" },
                    { value: "source", label: "Source" },
                    { value: "both", label: "Both" },
                  ]}
                  onPick={onViewChange}
                />
              </>
            )}
          </div>
        )}
      </div>

      {advanced && (
        <Advanced
          prefs={prefs}
          onCancel={() => setAdvanced(false)}
          onSave={(p) => {
            onChange(p);
            setAdvanced(false);
          }}
        />
      )}
    </>
  );
}
