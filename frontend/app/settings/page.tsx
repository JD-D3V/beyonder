"use client";

import { useEffect, useState } from "react";
import { IconExternalLink, IconKeyRound } from "../../components/icons";
import {
  clearLlmConfig,
  getLlmConfig,
  PROVIDERS,
  setLlmConfig,
  type Provider,
} from "../../lib/llmKey";

export default function SettingsPage() {
  const [provider, setProvider] = useState<Provider>("gemini");
  const [key, setKey] = useState("");
  const [model, setModel] = useState("");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
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

  return (
    <div style={{ maxWidth: 520 }}>
      <h1>Settings</h1>
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
