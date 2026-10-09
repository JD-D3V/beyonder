"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import "../app/social.css";

type Status = "idle" | "playing" | "paused";

// Read-aloud with the browser's SpeechSynthesis. `getParagraphs` returns the
// DOM paragraphs of the chapter on screen; each is spoken in turn, highlighted
// and scrolled into view. Everything stops when `chapterKey` changes.
export default function TtsControls({
  chapterKey,
  getParagraphs,
}: {
  chapterKey: number;
  getParagraphs: () => HTMLElement[];
}) {
  const [supported, setSupported] = useState(false);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceURI, setVoiceURI] = useState("");
  const [rate, setRate] = useState(1);
  const [status, setStatus] = useState<Status>("idle");

  const run = useRef(0); // bumped to invalidate in-flight utterances
  const paras = useRef<HTMLElement[]>([]);
  const pos = useRef(0);
  const stale = useRef(false); // voice/speed changed while paused
  const cur = useRef<HTMLElement | null>(null);
  const opts = useRef({ voiceURI: "", rate: 1, voices: [] as SpeechSynthesisVoice[] });
  opts.current = { voiceURI, rate, voices };
  const getRef = useRef(getParagraphs);
  getRef.current = getParagraphs;

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    setSupported(true);
    const synth = window.speechSynthesis;
    const load = () => {
      const all = synth.getVoices();
      const en = all.filter((v) => v.lang.toLowerCase().startsWith("en"));
      const rest = all.filter((v) => !v.lang.toLowerCase().startsWith("en"));
      const sorted = [...en, ...rest];
      setVoices(sorted);
      setVoiceURI((v) => v || sorted[0]?.voiceURI || "");
    };
    load();
    synth.addEventListener?.("voiceschanged", load);
    return () => synth.removeEventListener?.("voiceschanged", load);
  }, []);

  const clearMark = () => {
    cur.current?.classList.remove("tts-active");
    cur.current = null;
  };

  const stop = useCallback(() => {
    run.current++;
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    clearMark();
    pos.current = 0;
    stale.current = false;
    setStatus("idle");
  }, []);

  const speakAt = useCallback((i: number) => {
    const synth = window.speechSynthesis;
    const list = paras.current;
    clearMark();
    // Skip blank paragraphs.
    while (i < list.length && !(list[i].textContent || "").trim()) i++;
    if (i >= list.length) {
      run.current++;
      pos.current = 0;
      setStatus("idle");
      return;
    }
    const token = ++run.current;
    pos.current = i;
    const el = list[i];
    el.classList.add("tts-active");
    cur.current = el;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    const u = new SpeechSynthesisUtterance((el.textContent || "").trim());
    const o = opts.current;
    const v = o.voices.find((x) => x.voiceURI === o.voiceURI);
    if (v) {
      u.voice = v;
      u.lang = v.lang;
    }
    u.rate = o.rate;
    u.onend = () => {
      if (run.current === token) speakAt(i + 1);
    };
    u.onerror = (ev) => {
      if (run.current !== token) return;
      if (ev.error === "canceled" || ev.error === "interrupted") return;
      speakAt(i + 1);
    };
    synth.cancel();
    synth.speak(u);
    setStatus("playing");
  }, []);

  function play() {
    const synth = window.speechSynthesis;
    if (status === "paused") {
      if (stale.current) {
        // Re-speak the current paragraph with the new voice/speed. Clear the
        // engine's paused flag first or the new utterance would stay silent.
        stale.current = false;
        synth.cancel();
        synth.resume();
        speakAt(pos.current);
        return;
      }
      synth.resume();
      setStatus("playing");
      return;
    }
    paras.current = getRef.current();
    if (paras.current.length === 0) return;
    speakAt(0);
  }

  function pause() {
    window.speechSynthesis.pause();
    setStatus("paused");
  }

  // Voice/speed changes apply from the paragraph being read; while paused
  // they wait for Resume so playback never starts on its own.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (status === "playing") speakAt(pos.current);
    else if (status === "paused") stale.current = true; // applied on resume
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rate, voiceURI]);

  // Chapter change and unmount both stop speech.
  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        run.current++;
        window.speechSynthesis.cancel();
      }
      cur.current?.classList.remove("tts-active");
      cur.current = null;
      pos.current = 0;
      stale.current = false;
      setStatus("idle");
    };
  }, [chapterKey]);

  if (!supported) return null;

  return (
    <span className="tts-bar" role="group" aria-label="Read aloud">
      {status === "playing" ? (
        <button className="secondary" onClick={pause} title="Pause reading aloud">
          Pause
        </button>
      ) : (
        <button className="secondary" onClick={play} title="Read this chapter aloud">
          {status === "paused" ? "Resume" : "Listen"}
        </button>
      )}
      {status !== "idle" && (
        <button className="secondary" onClick={stop} title="Stop reading aloud">
          Stop
        </button>
      )}
      <label className="small" title="Speech speed">
        <input
          type="range"
          min={0.5}
          max={2}
          step={0.25}
          value={rate}
          onChange={(e) => setRate(Number(e.target.value))}
          aria-label="Speech speed"
        />{" "}
        {rate}x
      </label>
      {voices.length > 0 && (
        <select
          value={voiceURI}
          onChange={(e) => setVoiceURI(e.target.value)}
          aria-label="Voice"
        >
          {voices.map((v) => (
            <option key={v.voiceURI} value={v.voiceURI}>
              {v.name} ({v.lang})
            </option>
          ))}
        </select>
      )}
    </span>
  );
}
