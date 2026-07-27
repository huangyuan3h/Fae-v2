"use client";

import { AppNav } from "@/components/AppNav";

type Props = {
  showNav?: boolean;
};

export function AppHeader({ showNav = true }: Props) {
  return (
    <header
      className="sticky top-0 z-20 flex items-center justify-between border-b border-black/[0.06] bg-[color-mix(in_srgb,var(--bg-0)_82%,transparent)] px-4 py-2.5 backdrop-blur-md"
      data-testid="app-header"
    >
      <div className="flex items-center gap-2">
        <span
          className="grid h-7 w-7 place-items-center rounded-lg text-xs font-extrabold text-white"
          style={{
            background:
              "radial-gradient(circle at 30% 30%, #5fd0ad, var(--orb) 55%, #0b4d3c)",
            fontFamily: "var(--font-display)",
          }}
          aria-hidden
        >
          F
        </span>
        <span
          className="text-base font-extrabold tracking-tight text-[var(--ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          FAE
        </span>
      </div>
      {showNav && <AppNav />}
    </header>
  );
}