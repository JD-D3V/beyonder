// The user's own AI provider key. It stays in this browser and is sent only
// with AI requests; the server never stores it.

const KEY = "beyonder.llm";

export const PROVIDERS = [
  "gemini",
  "openrouter",
  "groq",
  "deepseek",
  "openai",
] as const;

export type Provider = (typeof PROVIDERS)[number];

export interface LlmConfig {
  provider: Provider;
  key: string;
  model?: string;
}

export function getLlmConfig(): LlmConfig | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const c = JSON.parse(raw) as LlmConfig;
    if (!c || !c.key || !(PROVIDERS as readonly string[]).includes(c.provider)) {
      return null;
    }
    return c;
  } catch {
    return null;
  }
}

export function setLlmConfig(config: LlmConfig): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(config));
  } catch {
    // ignore
  }
}

export function clearLlmConfig(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
