"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { IconLogIn, IconLogOut, IconSettings } from "./icons";
import {
  clearSession,
  getSession,
  SESSION_EVENT,
  UNAUTHORIZED_EVENT,
  type Session,
} from "../lib/session";

const LINKS = [
  { href: "/", label: "Catalog" },
  { href: "/library", label: "My Library" },
  { href: "/import", label: "Import" },
  { href: "/reader", label: "Reader" },
  { href: "/glossary", label: "Glossary" },
  { href: "/kg", label: "Knowledge Graph" },
  { href: "/eval", label: "Eval" },
];

export default function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);

  // Read storage after mount so the static HTML and first render match.
  useEffect(() => {
    const sync = () => setSession(getSession());
    sync();
    window.addEventListener(SESSION_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(SESSION_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  // A 401 anywhere (expired session, or an action that needs one) sends the
  // reader to sign in, then back to where they were.
  useEffect(() => {
    const onUnauthorized = () => {
      if (pathname.startsWith("/login")) return;
      const here = pathname + window.location.search + window.location.hash;
      router.replace(`/login?next=${encodeURIComponent(here)}`);
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [pathname, router]);

  async function signOut() {
    try {
      await api.logout();
    } catch {
      // Sign out locally even if the server cannot be reached.
    }
    clearSession();
    router.push("/login");
  }

  return (
    <nav className="topnav">
      <span className="brand">Beyonder</span>
      <div className="links">
        {LINKS.map((l) => {
          const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          return (
            <Link key={l.href} href={l.href} className={active ? "active" : ""}>
              {l.label}
            </Link>
          );
        })}
        <Link href="/settings" className={pathname.startsWith("/settings") ? "active" : ""}>
          <IconSettings size={16} /> Settings
        </Link>
        {session ? (
          <>
            <span className="muted small">{session.user.email}</span>
            <a href="#" onClick={(e) => { e.preventDefault(); void signOut(); }}>
              <IconLogOut size={16} /> Sign out
            </a>
          </>
        ) : (
          <Link href="/login" className={pathname.startsWith("/login") ? "active" : ""}>
            <IconLogIn size={16} /> Sign in
          </Link>
        )}
      </div>
    </nav>
  );
}
