import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANT_STYLE: Record<Variant, React.CSSProperties> = {
  primary: { background: "var(--accent)", color: "#fff", border: "1px solid transparent" },
  secondary: {
    background: "rgba(255,255,255,0.7)",
    color: "var(--ink)",
    border: "1px solid rgba(0,0,0,0.1)",
  },
  ghost: {
    background: "transparent",
    color: "var(--ink-soft)",
    border: "1px solid transparent",
  },
  danger: { background: "var(--danger)", color: "#fff", border: "1px solid transparent" },
};

const SIZE_CLASS: Record<Size, string> = {
  sm: "rounded-md px-2.5 py-1 text-xs",
  md: "rounded-full px-4 py-2 text-sm",
  lg: "rounded-full px-5 py-3 text-sm font-semibold",
};

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  leading?: ReactNode;
  trailing?: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  leading,
  trailing,
  className = "",
  style,
  children,
  ...rest
}: Props) {
  const variantStyle = VARIANT_STYLE[variant];
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-1.5 transition hover:opacity-90 disabled:opacity-50 ${SIZE_CLASS[size]} ${className}`}
      style={{ ...variantStyle, ...style }}
    >
      {leading}
      {children}
      {trailing}
    </button>
  );
}