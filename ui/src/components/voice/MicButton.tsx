"use client";

type Props = {
  active: boolean;
  disabled?: boolean;
  onStart: () => void;
  onStop: () => void;
};

export function MicButton({ active, disabled, onStart, onStop }: Props) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => (active ? onStop() : onStart())}
      className="rounded-full px-6 py-3 text-sm font-semibold text-white transition disabled:opacity-40"
      style={{
        background: active ? "var(--danger)" : "var(--accent)",
        fontFamily: "var(--font-body)",
      }}
      aria-pressed={active}
    >
      {active ? "停止聆听" : "开始说话"}
    </button>
  );
}
