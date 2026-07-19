"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { getSchedulerStatus } from "@/lib/schedules-api";

const LINKS = [
  { href: "/", label: "对话", exact: true },
  { href: "/memory", label: "记忆", exact: false },
  { href: "/skills", label: "Skills", exact: false },
  { href: "/schedules", label: "日程", exact: false },
  { href: "/settings", label: "Settings", exact: false },
] as const;

function isActive(pathname: string, href: string, exact: boolean): boolean {
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppNav({ className = "" }: { className?: string }) {
  const pathname = usePathname() || "/";
  const statusQ = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: getSchedulerStatus,
    refetchInterval: 30_000,
    retry: false,
  });
  const unread = statusQ.data?.unread_inbox ?? 0;

  return (
    <nav
      className={`flex flex-wrap items-center justify-center gap-2 text-sm ${className}`}
      aria-label="Primary"
    >
      {LINKS.map((link) => {
        const active = isActive(pathname, link.href, link.exact);
        const isSettings = link.href === "/settings";
        const showBadge = isSettings && unread > 0;
        const href = showBadge
          ? "/settings?tab=notifications"
          : link.href;
        return (
          <Link
            key={link.href}
            href={href}
            className="relative rounded-full px-3 py-1.5 transition"
            style={{
              background: active ? "var(--accent)" : "transparent",
              color: active ? "#fff" : "var(--ink-soft)",
              border: active ? "none" : "1px solid rgba(0,0,0,0.1)",
            }}
            title={
              showBadge
                ? `${unread} 条未读通知（Settings → 通知）`
                : undefined
            }
          >
            {link.label}
            {showBadge && (
              <span
                className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--danger)] px-1 text-[10px] font-semibold text-white"
                data-testid="nav-unread-badge"
              >
                {unread > 9 ? "9+" : unread}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}
