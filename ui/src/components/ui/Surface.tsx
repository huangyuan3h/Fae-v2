import type { HTMLAttributes, ReactNode } from "react";

type Props = HTMLAttributes<HTMLDivElement> & {
  tone?: "default" | "subtle" | "raised" | "warning" | "danger";
  children: ReactNode;
};

const TONE: Record<NonNullable<Props["tone"]>, string> = {
  default: "bg-white/70",
  subtle: "bg-white/45",
  raised: "bg-white/85",
  warning: "bg-amber-50/80",
  danger: "bg-[color-mix(in_srgb,var(--danger)_8%,white/70%)]",
};

export function Surface({
  tone = "default",
  className = "",
  style,
  children,
  ...rest
}: Props) {
  return (
    <div
      {...rest}
      className={`rounded-2xl border border-black/10 backdrop-blur-md ${TONE[tone]} ${className}`}
      style={style}
    >
      {children}
    </div>
  );
}

export function Card({
  className = "",
  style,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={`rounded-2xl border border-black/10 bg-white/80 p-4 backdrop-blur-md shadow-sm ${className}`}
      style={style}
    >
      {children}
    </div>
  );
}