import type { CSSProperties, HTMLAttributes, ReactNode } from "react";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "muted";

const TONE_STYLE: Record<Tone, CSSProperties> = {
  neutral: { background: "rgba(0,0,0,0.05)", color: "var(--ink)", border: "1px solid rgba(0,0,0,0.08)" },
  accent: { background: "var(--accent-soft)", color: "var(--accent)", border: "1px solid transparent" },
  success: { background: "rgba(16,185,129,0.12)", color: "#047857", border: "1px solid transparent" },
  warning: { background: "rgba(245,158,11,0.14)", color: "#92400e", border: "1px solid transparent" },
  danger: { background: "rgba(180,35,24,0.10)", color: "var(--danger)", border: "1px solid transparent" },
  muted: { background: "transparent", color: "var(--ink-soft)", border: "1px solid rgba(0,0,0,0.08)" },
};

const DOT_COLOR: Record<Tone, string> = {
  neutral: "var(--ink-soft)",
  accent: "var(--accent)",
  success: "#10b981",
  warning: "#f59e0b",
  danger: "var(--danger)",
  muted: "var(--ink-soft)",
};

type Props = HTMLAttributes<HTMLSpanElement> & {
  tone?: Tone;
  dot?: boolean;
  pulse?: boolean;
  children: ReactNode;
};

export function Badge({
  tone = "neutral",
  dot = false,
  pulse = false,
  className = "",
  style,
  children,
  ...rest
}: Props) {
  const toneStyle = TONE_STYLE[tone];
  return (
    <span
      {...rest}
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium leading-none ${className}`}
      style={{ ...toneStyle, ...style }}
    >
      {dot && (
        <span
          className={pulse ? "h-1.5 w-1.5 rounded-full animate-pulse" : "h-1.5 w-1.5 rounded-full"}
          style={{ background: DOT_COLOR[tone] }}
        />
      )}
      {children}
    </span>
  );
}

export function statusTone(status: string): Tone {
  switch (status) {
    case "running":
    case "thinking":
      return "accent";
    case "done":
    case "approved":
      return "success";
    case "awaiting_approval":
      return "warning";
    case "error":
    case "denied":
    case "expired":
      return "danger";
    case "cancelled":
      return "muted";
    default:
      return "neutral";
  }
}