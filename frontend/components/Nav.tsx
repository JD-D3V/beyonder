"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/reader", label: "Reader" },
  { href: "/glossary", label: "Glossary" },
  { href: "/kg", label: "Knowledge Graph" },
  { href: "/eval", label: "Eval" },
];

export default function Nav() {
  const pathname = usePathname();
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
      </div>
    </nav>
  );
}
