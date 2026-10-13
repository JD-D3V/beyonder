"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { IconLogIn, IconLogOut, IconMoon, IconSettings, IconSun } from "./icons";
import {
  applySiteTheme,
  loadSiteTheme,
  resolveSiteTheme,
  saveSiteTheme,
  SITE_THEME_EVENT,
  type SiteTheme,
} from "../lib/siteTheme";
import {
  clearSession,
  getSession,
  SESSION_EVENT,
  UNAUTHORIZED_EVENT,
  type Session,
} from "../lib/session";

const PRIMARY = [
  { href: "/", label: "Catalog" },
  { href: "/rankings", label: "Rankings" },
  { href: "/library", label: "My Library" },
];

const SECONDARY = [
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
  const [theme, setTheme] = useState<SiteTheme>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("dark");
  const [open, setOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  // Close on navigation.
  useEffect(() => setOpen(false), [pathname]);

  // Escape closes (and returns focus); so does a click or focus outside.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    };
    const onOutside = (e: Event) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onOutside);
    document.addEventListener("focusin", onOutside);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onOutside);
      document.removeEventListener("focusin", onOutside);
    };
  }, [open]);

  // Follow the stored choice (and the OS when set to System).
  useEffect(() => {
    const sync = () => {
      const t = loadSiteTheme();
      setTheme(t);
      setResolved(resolveSiteTheme(t));
      applySiteTheme(t);
    };
    sync();
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    window.addEventListener(SITE_THEME_EVENT, sync);
    window.addEventListener("storage", sync);
    mq.addEventListener("change", sync);
    return () => {
      window.removeEventListener(SITE_THEME_EVENT, sync);
      window.removeEventListener("storage", sync);
      mq.removeEventListener("change", sync);
    };
  }, []);

  // Cycle System -> Light -> Dark.
  function cycleTheme() {
    saveSiteTheme(theme === "system" ? "light" : theme === "light" ? "dark" : "system");
  }

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

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);
  const cls = (href: string) => (isActive(href) ? "active" : "");

  return (
    <nav className="topnav">
      <span className="brand">Beyonder</span>
      <div className="links">
        {PRIMARY.map((l) => (
          <Link key={l.href} href={l.href} className={cls(l.href)}>
            {l.label}
          </Link>
        ))}
      </div>
      <div className="more" ref={moreRef}>
        <button
          ref={toggleRef}
          type="button"
          className="secondary more-toggle"
          aria-expanded={open}
          aria-haspopup="true"
          aria-controls="more-menu"
          aria-label="More"
          onClick={() => setOpen((o) => !o)}
        >
          <svg className="more-burger" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
          <span className="more-label">More</span>
        </button>
        {open && (
          <div id="more-menu" className="more-menu">
            {SECONDARY.map((l) => (
              <Link key={l.href} href={l.href} className={cls(l.href)}>
                {l.label}
              </Link>
            ))}
            {session?.user.is_admin && (
              <Link href="/admin" className={cls("/admin")}>
                Admin
              </Link>
            )}
            <Link href="/settings" className={cls("/settings")}>
              <IconSettings size={16} /> Settings
            </Link>
            <hr />
            {session ? (
              <>
                <span className="muted small more-email">{session.user.email}</span>
                <button type="button" className="more-item" onClick={() => { setOpen(false); void signOut(); }}>
                  <IconLogOut size={16} /> Sign out
                </button>
              </>
            ) : (
              <Link href="/login" className={cls("/login")}>
                <IconLogIn size={16} /> Sign in
              </Link>
            )}
            <button
              type="button"
              className="more-item"
              onClick={cycleTheme}
              title={`Website theme: ${theme}. Click to change.`}
              aria-label={`Website theme: ${theme}. Click to change.`}
            >
              {resolved === "light" ? <IconSun size={16} /> : <IconMoon size={16} />}
              Theme: {theme === "system" ? "System" : theme === "light" ? "Light" : "Dark"}
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
