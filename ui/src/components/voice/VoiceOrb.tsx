"use client";

import { motion } from "framer-motion";

import type { OrbState } from "@/hooks/useVoiceSession";

const LABEL: Record<OrbState, string> = {
  idle: "ready",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
};

export function VoiceOrb({ state }: { state: OrbState }) {
  const pulse =
    state === "listening"
      ? [1, 1.08, 1]
      : state === "speaking"
        ? [1, 1.12, 0.96, 1.08, 1]
        : state === "thinking"
          ? [1, 1.04, 1]
          : [1, 1.02, 1];

  const rotate =
    state === "thinking" || state === "speaking" ? [0, 180, 360] : [0, 8, 0];

  return (
    <div className="relative grid place-items-center">
      <motion.div
        aria-hidden
        className="absolute h-56 w-56 rounded-full"
        style={{
          background:
            "radial-gradient(circle, var(--glow) 0%, transparent 70%)",
        }}
        animate={{ opacity: state === "idle" ? 0.45 : 0.9, scale: pulse }}
        transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        role="img"
        aria-label={`FAE orb ${LABEL[state]}`}
        className="relative grid h-40 w-40 place-items-center rounded-full"
        style={{
          background:
            "radial-gradient(circle at 30% 30%, #5fd0ad, var(--orb) 55%, #0b4d3c)",
          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.25)",
        }}
        animate={{ scale: pulse, rotate }}
        transition={{
          scale: { duration: state === "speaking" ? 1.2 : 2.8, repeat: Infinity },
          rotate: {
            duration: state === "thinking" ? 6 : 14,
            repeat: Infinity,
            ease: "linear",
          },
        }}
      >
        <span
          className="text-sm uppercase tracking-[0.35em] text-white/90"
          style={{ fontFamily: "var(--font-display)" }}
        >
          FAE
        </span>
      </motion.div>
      <p className="mt-6 text-sm tracking-wide text-[var(--ink-soft)]">
        {LABEL[state]}
      </p>
    </div>
  );
}
