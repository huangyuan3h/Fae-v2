import type { ButtonHTMLAttributes, ReactNode } from "react";

type Size = "sm" | "md" | "lg";

const SIZE_CLASS: Record<Size, string> = {
  sm: "h-7 w-7",
  md: "h-10 w-10",
  lg: "h-12 w-12",
};

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  size?: Size;
  active?: boolean;
  label: string;
  children: ReactNode;
};

export function IconButton({
  size = "md",
  active = false,
  label,
  className = "",
  style,
  children,
  ...rest
}: Props) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...rest}
      className={`grid place-items-center rounded-full transition disabled:opacity-50 ${SIZE_CLASS[size]} ${className}`}
      style={{
        background: active ? "var(--accent)" : "rgba(255,255,255,0.75)",
        color: active ? "#fff" : "var(--ink)",
        border: "1px solid rgba(0,0,0,0.1)",
        boxShadow: active ? "0 6px 18px var(--glow)" : "none",
        ...style,
      }}
    >
      {children}
    </button>
  );
}