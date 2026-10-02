"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { IconLogIn, IconUser } from "../../components/icons";
import { api } from "../../lib/api";
import { setSession } from "../../lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invite, setInvite] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r =
        mode === "signin"
          ? await api.login({ email: email.trim(), password })
          : await api.signup({ email: email.trim(), password, invite: invite.trim() });
      setSession({ token: r.token, user: r.user });
      router.push("/");
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ maxWidth: 420 }}>
      <h1>{mode === "signin" ? "Sign in" : "Create an account"}</h1>
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            autoComplete="email"
            required
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            required
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {mode === "signup" && (
          <div className="field">
            <label htmlFor="invite">Invite code</label>
            <input
              id="invite"
              type="text"
              value={invite}
              required
              onChange={(e) => setInvite(e.target.value)}
            />
          </div>
        )}
        {err && <div className="error">{err}</div>}
        <div className="row">
          <button type="submit" disabled={busy}>
            {mode === "signin" ? <IconLogIn /> : <IconUser />}{" "}
            <span>{busy ? "Working..." : mode === "signin" ? "Sign in" : "Sign up"}</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setErr(null);
            }}
          >
            {mode === "signin" ? "Have an invite? Sign up" : "Back to sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
