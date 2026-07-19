"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "对话", exact: true },
  { href: "/memory", label: "记忆", exact: false },
  { href: "/skills", label: "Skills", exact: false },
  { href: "/schedules", label: "日程", exact: false, soon: true },
  { href: "/settings", label: "Settings", exact: false },
] as const;

function isActive(pathname: string, href: string, exact: boolean): boolean {
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppNav({ className = "" }: { className?: string }) {
  const pathname = usePathname() || "/";
  return (
    <nav
      className={`flex flex-wrap items-center justify-center gap-2 text-sm ${className}`}
      aria-label="Primary"
    >
      {LINKS.map((link) => {
        const active = isActive(pathname, link.href, link.exact);
        const soon = "soon" in link && link.soon;
        if (soon) {
          return (
            <span
              key={link.href}
              className="rounded-full px-3 py-1.5 text-[var(--ink-soft)] opacity-60"
              title="Phase 4"
            >
              {link.label}
            </span>
          );
        }
        return (
          <Link
            key={link.href}
            href={link.href}
            className="rounded-full px-3 py-1.5 transition"
            style={{
              background: active ? "var(--accent)" : "transparent",
              color: active ? "#fff" : "var(--ink-soft)",
              border: active ? "none" : "1px solid rgba(0,0,0,0.1)",
            }}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
