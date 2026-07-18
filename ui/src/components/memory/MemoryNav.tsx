"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/memory", label: "时间线" },
  { href: "/memory/facts", label: "事实" },
  { href: "/memory/search", label: "搜索" },
] as const;

export function MemoryNav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-wrap items-center gap-2 border-b border-black/10 pb-4">
      <Link
        href="/"
        className="mr-2 text-sm text-[var(--ink-soft)] underline-offset-2 hover:underline"
      >
        ← FAE
      </Link>
      {LINKS.map((link) => {
        const active = pathname === link.href;
        return (
          <Link
            key={link.href}
            href={link.href}
            className="rounded-full px-3 py-1.5 text-sm transition"
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
