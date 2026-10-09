"use client";

import { useEffect, useState } from "react";
import { siteApi } from "../../lib/api-site";
import { getSession, setSession } from "../../lib/session";
import { IconExternalLink, IconKeyRound } from "../../components/icons";
import {
  clearLlmConfig,
  getLlmConfig,
  PROVIDERS,
  setLlmConfig,
  type Provider,
} from "../../lib/llmKey";
import {
  applySiteTheme,
  loadSiteTheme,
  saveSiteTheme,
  type SiteTheme,
} from "../../lib/siteTheme";

export default function SettingsPage() {
  const [provider, setProvider] = useState<Provider>("gemini");
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [siteTheme, setSiteTheme] = useState<SiteTheme>("system");
  const [signedIn, setSignedIn] = useState(false);
  const [pubName, setPubName] = useState("");
  const [nameNote, setNameNote] = useState<string | null>(null);

  useEffect(() => {
    setSiteTheme(loadSiteTheme());
    const sess = getSession();
    setSignedIn(!!sess);
    setPubName(sess?.user.display_name || "");
    const c = getLlmConfig();
    if (c) {
      setProvider(c.provider);
      setKey(c.key);
      setModel(c.model || "");
    }
  }, []);

  function save() {
    if (!key.trim()) {
      setNote("Paste a key first.");
      return;
    }
    setLlmConfig({
      provider,
      key: key.trim(),
      model: model.trim() || undefined,
    });
    setNote("Saved in this browser.");
  }

  function remove() {
    clearLlmConfig();
    setKey("");
    setModel("");
    setNote("Key removed.");
  }

  async function saveName() {
    setNameNote(null);
    try {
      const u = await siteApi.setDisplayName(pubName.trim() || null);
      const sess = getSession();
      if (sess) setSession({ ...sess, user: { ...sess.user, display_name: u.display_name ?? null } });
      setPubName(u.display_name || "");
      setNameNote(u.display_name ? "Public name saved." : "Public name cleared.");
    } catch (e) {
      setNameNote(e instanceof Error ? e.message : "Could not save.");
    }
  }

  function chooseTheme(t: SiteTheme) {
    setSiteTheme(t);
    saveSiteTheme(t);
    applySiteTheme(t);
  }

  return (
    <div style={{ maxWidth: 520 }}>
      <h1>Settings</h1>
      <h2>Website theme</h2>
      <p className="small muted">
        Applies to the whole site. The reader has its own theme in its display settings.
      </p>
      <div className="seg" style={{ width: "fit-content", marginBottom: 18 }}>
        {(["light", "dark", "system"] as const).map((t) => (
          <button
            key={t}
            type="button"
            className={siteTheme === t ? "on" : ""}
            aria-pressed={siteTheme === t}
            onClick={() => chooseTheme(t)}
          >
            {t === "light" ? "Light" : t === "dark" ? "Dark" : "System"}
          </button>
        ))}
      </div>
      {signedIn && (
        <>
          <h2>Public name</h2>
          <p className="small muted">
            Shown on your reviews and comments. 3-24 letters, digits, - or _.
            If blank you appear as reader-&lt;number&gt;. Your email is never shown.
          </p>
          <div className="field">
            <label htmlFor="public-name">Public name</label>
            <input
              id="public-name"
              type="text"
              value={pubName}
              maxLength={24}
              autoComplete="nickname"
              onChange={(e) => setPubName(e.target.value)}
            />
          </div>
          {nameNote && <div className="notice" role="status">{nameNote}</div>}
          <div className="row" style={{ marginBottom: 18 }}>
            <button onClick={saveName}>Save name</button>
          </div>
        </>
      )}
      <h2>AI key</h2>
      <p className="small muted">
        Translation and questions use your own AI key. The key stays in this
        browser and is sent only with AI requests. The server never stores it.
      </p>
      <div className="field">
        <label htmlFor="provider">Provider</label>
        <select
          id="provider"
          value={provider}
          onChange={(e) => setProvider(e.target.value as Provider)}
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="key">API key</label>
        <input
          id="key"
          type="password"
          value={key}
          autoComplete="off"
          onChange={(e) => setKey(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="model">Model (optional)</label>
        <input
          id="model"
          type="text"
          value={model}
          placeholder="Leave blank for the default"
          onChange={(e) => setModel(e.target.value)}
        />
      </div>
      {note && <div className="notice">{note}</div>}
      <div className="row">
        <button onClick={save}><IconKeyRound /> <span>Save</span></button>
        <button onClick={remove}>Remove key</button>
      </div>

      <h2>Get a free Gemini key</h2>
      <ol className="small">
        <li>
          Open{" "}
          <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
            aistudio.google.com/apikey <IconExternalLink size={14} />
          </a>{" "}
          and sign in with a Google account.
        </li>
        <li>Choose Create API key.</li>
        <li>Copy the key, paste it above, pick gemini, and save.</li>
      </ol>
    </div>
  );
}
